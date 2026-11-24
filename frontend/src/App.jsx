import { useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  Building2,
  Eye,
  EyeOff,
  Layers3,
  LockKeyhole,
  Mail,
  Phone,
  UserRound
} from "lucide-react";
import "./App.css";

const API_BASE = (
  import.meta.env.VITE_API_URL || "http://127.0.0.1:8000"
).replace(/\/$/, "");

const ACCOUNT_TYPES = [
  { value: "foreign_buyer", label: "Foreign buyer / brands" },
  { value: "buying_house", label: "Buying house" },
  { value: "textile_supplier", label: "Textile and fabric suppliers" },
  { value: "admin_authority", label: "Admin / authority" }
];

function AccountTypeOptions({ accountType, onSelect, className = "" }) {
  return (
    <nav
      className={`role-selector ${className}`}
      aria-label="Choose account type to log in"
    >
      <p className="role-selector-heading">Log in as</p>
      <div className="role-options">
        {ACCOUNT_TYPES.map((type) => (
          <button
            key={type.value}
            type="button"
            className={`role-option${accountType === type.value ? " is-active" : ""}`}
            aria-pressed={accountType === type.value}
            onClick={() => onSelect(type.value)}
          >
            {type.label}
          </button>
        ))}
      </div>
    </nav>
  );
}

function Brand() {
  return (
    <div className="brand">
      <div className="brand-icon">
        <Layers3 size={24} />
      </div>
      <span>
        TEX<span className="brand-light">TECH</span>
      </span>
    </div>
  );
}

function readVerificationFragment() {
  const fragment = window.location.hash.slice(1);
  if (!fragment.startsWith("verify-email=")) return null;
  const parameters = new URLSearchParams(fragment);
  return parameters.get("verify-email") || "";
}

function clearVerificationFragment() {
  if (!window.location.hash.slice(1).startsWith("verify-email=")) return;
  const remaining = window.location.hash.slice(1).split("&")
    .filter((part) => part.split("=")[0] !== "verify-email").join("&");
  window.history.replaceState(window.history.state, "",
    `${window.location.pathname}${window.location.search}${remaining ? `#${remaining}` : ""}`);
}

function readResetFragment() {
  const fragment = window.location.hash.slice(1);
  if (!fragment.startsWith("reset-password=")) return null;
  return new URLSearchParams(fragment).get("reset-password") || "";
}

function clearResetFragment() {
  if (!window.location.hash.slice(1).startsWith("reset-password=")) return;
  const remaining = window.location.hash.slice(1).split("&")
    .filter((part) => part.split("=")[0] !== "reset-password").join("&");
  window.history.replaceState(window.history.state, "",
    `${window.location.pathname}${window.location.search}${remaining ? `#${remaining}` : ""}`);
}

const RESET_REQUEST_NOTICE = "If an account exists for this email, a password-reset link may arrive. Check your inbox and spam folder.";

function App() {
  const [isSignup, setIsSignup] = useState(false);
  const [isForgotPassword, setIsForgotPassword] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [accountType, setAccountType] = useState("foreign_buyer");
  const [formData, setFormData] = useState({
    fullName: "",
    email: "",
    phone: "",
    company: "",
    password: "",
    confirmPassword: "",
    terms: false
  });
  const [message, setMessage] = useState("");
  const [messageType, setMessageType] = useState("");
  const [loading, setLoading] = useState(false);
  const [verificationToken, setVerificationToken] = useState(readVerificationFragment);
  const [verificationResult, setVerificationResult] = useState("ready");
  const [signupNotice, setSignupNotice] = useState(null);
  const [resetToken, setResetToken] = useState(readResetFragment);
  const [resetResult, setResetResult] = useState("ready");
  const isReset = resetToken !== null;
  const resetScreen = useRef(isReset);
  const pendingRequest = useRef(null);
  const screenVersion = useRef(0);
  const isVerification = verificationToken !== null;

  function cancelPending() {
    screenVersion.current += 1;
    pendingRequest.current?.abort();
    pendingRequest.current = null;
    setLoading(false);
  }

  useEffect(() => {
    function onHashChange() {
      screenVersion.current += 1;
      pendingRequest.current?.abort();
      pendingRequest.current = null;
      setLoading(false);
      setVerificationToken(readVerificationFragment());
      const nextReset = readResetFragment();
      if (resetScreen.current || nextReset !== null) {
        setFormData((current) => ({ ...current, password: "", confirmPassword: "" }));
        setShowPassword(false);
        setShowConfirmPassword(false);
      }
      resetScreen.current = nextReset !== null;
      setResetToken(nextReset);
      setResetResult("ready");
      setVerificationResult("ready");
      setSignupNotice(null);
      setMessage("");
      setMessageType("");
    }
    window.addEventListener("hashchange", onHashChange);
    return () => {
      window.removeEventListener("hashchange", onHashChange);
      screenVersion.current += 1;
      pendingRequest.current?.abort();
      pendingRequest.current = null;
    };
  }, []);

  function leaveVerification() {
    cancelPending();
    clearVerificationFragment();
    clearResetFragment();
    setResetToken(null);
    setResetResult("ready");
    if (resetScreen.current || isForgotPassword) {
      setFormData((current) => ({ ...current, password: "", confirmPassword: "" }));
      setShowPassword(false);
      setShowConfirmPassword(false);
    }
    resetScreen.current = false;
    setVerificationToken(null);
    setVerificationResult("ready");
    setSignupNotice(null);
    setIsSignup(false);
    setIsForgotPassword(false);
    setMessage("");
    setMessageType("");
  }

  async function handleVerify() {
    if (pendingRequest.current || verificationResult !== "ready") return;
    const controller = new AbortController();
    const version = screenVersion.current;
    pendingRequest.current = controller;
    const stillCurrent = () => version === screenVersion.current && !controller.signal.aborted;
    setLoading(true);
    setMessage("");
    try {
      const data = await submitRequest("/api/auth/verify-email", { token: verificationToken },
        "Email verification could not be confirmed. Please try again.", controller.signal);
      if (!stillCurrent()) return;
      if (data.message !== "Email verified successfully") {
        throw new Error("Verification confirmation missing");
      }
      setVerificationResult("success");
      setVerificationToken("");
      clearVerificationFragment();
      setMessage("Your email is verified. You can now log in.");
      setMessageType("success");
    } catch (error) {
      if (!stillCurrent()) return;
      if (error.status === 400) {
        setVerificationResult("invalid");
        setVerificationToken("");
        clearVerificationFragment();
        setMessage("This verification link is invalid, expired, or already used. If you have already verified your email, return to login. Otherwise, a new link is needed; resend is not available yet.");
      } else {
        setMessage("Email verification could not be confirmed. The server may be temporarily unavailable. Try again; if the link was already processed, return to login.");
      }
      setMessageType("error");
    } finally {
      if (stillCurrent()) {
        pendingRequest.current = null;
        setLoading(false);
      }
    }
  }

  async function handleReset(event) {
    event.preventDefault();
    if (pendingRequest.current || resetResult !== "ready") return;
    setMessage("");
    setMessageType("");
    if (formData.password.length < 8 || formData.password.length > 128) {
      setMessage("Password must contain 8 to 128 characters.");
      setMessageType("error");
      return;
    }
    if (formData.password !== formData.confirmPassword) {
      setMessage("Passwords do not match.");
      setMessageType("error");
      return;
    }
    const controller = new AbortController();
    const version = screenVersion.current;
    pendingRequest.current = controller;
    const stillCurrent = () => version === screenVersion.current && !controller.signal.aborted;
    setLoading(true);
    try {
      const data = await submitRequest("/api/auth/reset-password",
        { token: resetToken, new_password: formData.password },
        "Password reset could not be confirmed.", controller.signal);
      if (!stillCurrent()) return;
      if (data.message !== "Password reset successfully. Log in with your new password; email verification is still required.") {
        throw new Error("Reset confirmation missing");
      }
      setResetResult("success");
      setResetToken("");
      clearResetFragment();
      setMessage("Your password has been reset. Return to login and use your new password. Email verification is still required.");
      setMessageType("success");
    } catch (error) {
      if (!stillCurrent()) return;
      if (error.status === 400) {
        setResetResult("invalid");
        setResetToken("");
        clearResetFragment();
        setMessage("This reset link is invalid, expired, or already used. If the reset was already processed, try logging in with your new password. Otherwise, request a new link.");
      } else if (error.status === 422) {
        setMessage("Password must contain 8 to 128 characters.");
      } else {
        setMessage("Password reset could not be confirmed. Try again later; if it was already processed, log in with your new password or request a new link.");
      }
      setMessageType("error");
    } finally {
      if (stillCurrent()) {
        setFormData((current) => ({ ...current, password: "", confirmPassword: "" }));
        pendingRequest.current = null;
        setLoading(false);
      }
    }
  }

  const selectedAccountType = ACCOUNT_TYPES.find(
    (type) => type.value === accountType
  );

  function handleChange(event) {
    const { name, value, type, checked } = event.target;
    setFormData((current) => ({
      ...current,
      [name]: type === "checkbox" ? checked : value
    }));
  }

  async function submitRequest(path, payload, fallback, signal) {
    const response = await fetch(`${API_BASE}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal
    });
    let data;
    try {
      data = await response.json();
    } catch {
      const error = new Error(fallback);
      error.status = response.status;
      throw error;
    }
    if (!response.ok) {
      // Use local messages: never display raw response bodies or validation inputs.
      const error = new Error(fallback);
      error.status = response.status;
      throw error;
    }
    if (!data || typeof data !== "object" || Array.isArray(data)) {
      throw new Error(fallback);
    }
    return data;
  }

  async function handleSubmit(event) {
    event.preventDefault();
    if (pendingRequest.current) return;
    setMessage("");
    setMessageType("");

    if (isSignup) {
      if (formData.password.length < 8) {
        setMessage("Password must contain at least 8 characters.");
        setMessageType("error");
        return;
      }
      if (formData.password !== formData.confirmPassword) {
        setMessage("Passwords do not match.");
        setMessageType("error");
        return;
      }
      if (!formData.terms) {
        setMessage("Please accept the terms and conditions.");
        setMessageType("error");
        return;
      }
    }

    const controller = new AbortController();
    const version = screenVersion.current;
    const submittingSignup = isSignup;
    const submittingForgot = isForgotPassword;
    pendingRequest.current = controller;
    const stillCurrent = () => version === screenVersion.current && !controller.signal.aborted;
    setLoading(true);
    try {
      if (isForgotPassword) {
        await submitRequest("/api/auth/forgot-password", { work_email: formData.email.trim() },
          "Reset request could not be confirmed. Please try again later.", controller.signal);
        if (!stillCurrent()) return;
        setMessage(RESET_REQUEST_NOTICE);
        setMessageType("info");
      } else if (isSignup) {
        const data = await submitRequest(
          "/api/auth/register",
          {
            full_name: formData.fullName.trim(),
            work_email: formData.email.trim(),
            phone: formData.phone.trim(),
            account_type: accountType,
            organization: formData.company.trim(),
            password: formData.password
          },
          "Registration could not be confirmed. Your account may have been created; do not immediately register again.",
          controller.signal
        );

        if (!stillCurrent()) return;
        const notices = {
          submitted: "Your account was created and a verification email was submitted. Check your inbox and spam folder. Use the email link to verify before logging in.",
          failed: "Your account was created, but the verification email could not be submitted. Do not register again. Verification is required before login; resend is not available yet.",
          uncertain: "Your account was created, but email submission could not be confirmed. The email may still arrive; check your inbox and spam folder. Verify before logging in. Do not register again; resend is not available yet."
        };
        const status = data.verification_email_status;
        setSignupNotice({
          text: Object.hasOwn(notices, status) ? notices[status] : "Your account was created, but email submission status is unknown. Check your inbox for a verification link. Verification is required before login; resend is not available yet.",
          type: status === "failed" ? "error" : "info"
        });
        setFormData((current) => ({
          ...current,
          fullName: "",
          phone: "",
          company: "",
          password: "",
          confirmPassword: "",
          terms: false
        }));
        setIsSignup(false);
      } else {
        const data = await submitRequest(
          "/api/auth/login",
          {
            work_email: formData.email.trim(),
            password: formData.password,
            account_type: accountType
          },
          "Login could not be completed. Please try again.",
          controller.signal
        );

        if (!stillCurrent()) return;
        if (typeof data.full_name !== "string" || !data.user_id) {
          throw new Error("Login confirmation missing");
        }
        setMessage(`Welcome back, ${data.full_name}.`);
        setMessageType("success");
        setFormData((current) => ({ ...current, password: "" }));
      }
    } catch (error) {
      if (!stillCurrent()) return;
      if (submittingForgot) {
        setMessage(error.status === 422 ? "Enter a valid work email address." : "Reset request could not be confirmed. Please try again later.");
        setMessageType("error");
        return;
      }
      let text = submittingSignup
        ? "Registration could not be confirmed. Your account may have been created; check your email before trying again."
        : "Login could not be completed. Please try again.";
      if (!submittingSignup && error.status === 403) {
        text = "Verify your email before logging in. Open the verification link in your email. If you need a new link, resend is not available yet.";
      } else if (!submittingSignup && error.status === 401) {
        text = "Invalid email, password, or account type.";
      } else if (submittingSignup && error.status === 409) {
        text = "An account with this email already exists. Do not register again. Verify using your email link before login; resend is not available yet.";
      } else if (error.status === 422) {
        text = "Please check your details and try again.";
      } else if (error.status === 503) {
        text = submittingSignup
          ? "Registration is temporarily unavailable. Check your email before trying again if account creation was interrupted."
          : "Login is temporarily unavailable. Please try again later.";
      }
      setMessage(text);
      setMessageType("error");
    } finally {
      if (stillCurrent()) {
        pendingRequest.current = null;
        setLoading(false);
      }
    }
  }

  function switchPage(showSignup) {
    leaveVerification();
    setIsSignup(showSignup);
    setIsForgotPassword(false);
    setMessage("");
    setMessageType("");
  }

  function chooseAccountType(value) {
    leaveVerification();
    setAccountType(value);
    setIsSignup(false);
    setIsForgotPassword(false);
    setMessage("");
    setMessageType("");
  }

  function showForgotPassword() {
    leaveVerification();
    setFormData((current) => ({ ...current, password: "", confirmPassword: "" }));
    setSignupNotice(null);
    setIsForgotPassword(true);
    setMessage("");
    setMessageType("");
  }

  return (
    <div className={`auth-page${isSignup || isVerification || isReset || signupNotice ? " signup-mode" : " login-mode"}`}>
      {!isSignup && !isVerification && !isReset && !signupNotice && (
        <aside className="role-sidebar">
          <Brand />
          <AccountTypeOptions
            accountType={accountType}
            onSelect={chooseAccountType}
          />
          <div className="sidebar-promo">
            <span className="eyebrow">TEXTECH FABRIC NETWORK</span>
            <h2>
              Better fabrics.
              <br />
              Better connections.
            </h2>
            <p>Bringing textile buyers and trusted suppliers together.</p>
          </div>
        </aside>
      )}

      <main className="auth-main">
        {isSignup && (
          <header className="signup-brand">
            <Brand />
          </header>
        )}

        {!isSignup && !isVerification && !isReset && !signupNotice && (
          <div className="mobile-role-selector">
            <AccountTypeOptions
              accountType={accountType}
              onSelect={chooseAccountType}
            />
          </div>
        )}

        {isReset ? (
          <section className="auth-card verification-card">
            <div className="form-heading">
              <span className="eyebrow">ACCOUNT RECOVERY</span>
              <h1>{resetResult === "success" ? "Password reset" : "Reset your password"}</h1>
              <p>Choose a new password. This link expires 30 minutes after it was issued.</p>
            </div>
            {resetResult === "ready" && (
              <form onSubmit={handleReset}>
                <div className="field">
                  <label htmlFor="resetPassword">New password</label>
                  <div className="input-wrap">
                    <LockKeyhole size={18} />
                    <input id="resetPassword" name="password" type={showPassword ? "text" : "password"}
                      value={formData.password} onChange={handleChange} autoComplete="new-password"
                      placeholder="8 to 128 characters" minLength={8} maxLength={128} required />
                    <button className="eye-button" type="button" onClick={() => setShowPassword((visible) => !visible)}
                      aria-label={showPassword ? "Hide password" : "Show password"}>
                      {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                    </button>
                  </div>
                </div>
                <div className="field">
                  <label htmlFor="resetConfirmPassword">Confirm new password</label>
                  <div className="input-wrap">
                    <LockKeyhole size={18} />
                    <input id="resetConfirmPassword" name="confirmPassword" type={showConfirmPassword ? "text" : "password"}
                      value={formData.confirmPassword} onChange={handleChange} autoComplete="new-password"
                      placeholder="Enter your new password again" minLength={8} maxLength={128} required />
                    <button className="eye-button" type="button" onClick={() => setShowConfirmPassword((visible) => !visible)}
                      aria-label={showConfirmPassword ? "Hide password" : "Show password"}>
                      {showConfirmPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                    </button>
                  </div>
                </div>
                <button className="submit-button" type="submit" disabled={loading}>
                  {loading ? "Resetting password..." : "Reset password"}
                </button>
              </form>
            )}
            {message && <div className={`form-message ${messageType}`} role={messageType === "error" ? "alert" : "status"} aria-live="polite">{message}</div>}
            {resetResult === "invalid" && <p className="login-prompt"><button className="form-link" type="button" onClick={showForgotPassword}>Request a new reset link</button></p>}
            <p className="login-prompt"><button className="form-link" type="button" onClick={leaveVerification}>Return to login</button></p>
          </section>
        ) : isVerification || signupNotice ? (
          <section className="auth-card verification-card">
            <div className="form-heading">
              <span className="eyebrow">EMAIL VERIFICATION</span>
              <h1>{signupNotice ? "Check your email" : verificationResult === "success" ? "Email verified" : "Verify your email"}</h1>
              <p>{signupNotice ? "Your account needs email verification before login." : "Confirm your email using the button below. Opening this page does not verify your account."}</p>
            </div>
            <div className={`form-message ${signupNotice?.type || messageType || "info"}`}
              role={(signupNotice?.type || messageType) === "error" ? "alert" : "status"} aria-live="polite">
              {signupNotice?.text || message || "This link expires 30 minutes after it was issued."}
            </div>
            {isVerification && verificationResult === "ready" && (
              <button className="submit-button" type="button" disabled={loading} onClick={handleVerify}>
                {loading ? "Verifying..." : "Verify email"}
              </button>
            )}
            <p className="login-prompt">
              <button className="form-link" type="button" onClick={leaveVerification}>Return to login</button>
            </p>
          </section>
        ) : (
        <section className="auth-card">
          <div className="form-heading">
            <span className="eyebrow">
              {isSignup
                ? "CREATE YOUR ACCOUNT"
                : isForgotPassword
                  ? "ACCOUNT RECOVERY"
                  : "WELCOME BACK"}
            </span>
            <h1>
              {isSignup
                ? "Create your account"
                : isForgotPassword
                  ? "Forgot your password?"
                  : "Sign in"}
            </h1>
            <p>
              {isSignup
                ? "Enter your details to set up your TexTech account."
                : isForgotPassword
                  ? "Enter the email address linked to your account."
                  : `Continue to TexTech as ${selectedAccountType.label}.`}
            </p>
          </div>

          <form onSubmit={handleSubmit}>
            {isSignup && (
              <div className="field">
                <label htmlFor="accountType">Account type</label>
                <select
                  id="accountType"
                  value={accountType}
                  onChange={(event) => { cancelPending(); setAccountType(event.target.value); }}
                >
                  {ACCOUNT_TYPES.map((type) => (
                    <option key={type.value} value={type.value}>
                      {type.label}
                    </option>
                  ))}
                </select>
              </div>
            )}

            {isSignup && (
              <div className="field">
                <label htmlFor="fullName">Full name</label>
                <div className="input-wrap">
                  <UserRound size={18} />
                  <input
                    id="fullName"
                    name="fullName"
                    type="text"
                    placeholder="Enter your full name"
                    value={formData.fullName}
                    onChange={handleChange}
                    autoComplete="name"
                    required
                  />
                </div>
              </div>
            )}

            <div className="field">
              <label htmlFor="email">
                {isForgotPassword ? "Email address" : "Work email address"}
              </label>
              <div className="input-wrap">
                <Mail size={18} />
                <input
                  id="email"
                  name="email"
                  type="email"
                  placeholder={
                    isForgotPassword ? "you@example.com" : "you@company.com"
                  }
                  value={formData.email}
                  onChange={handleChange}
                  autoComplete="email"
                  required
                />
              </div>
            </div>

            {isSignup && (
              <>
                <div className="field">
                  <label htmlFor="phone">Phone number</label>
                  <div className="input-wrap">
                    <Phone size={18} />
                    <input
                      id="phone"
                      name="phone"
                      type="tel"
                      placeholder="+880 1XXXXXXXXX"
                      value={formData.phone}
                      onChange={handleChange}
                      autoComplete="tel"
                      required
                    />
                  </div>
                  <span className="field-hint">
                    Use a number you can access for verification.
                  </span>
                </div>

                <div className="field">
                  <label htmlFor="company">Company / organization name</label>
                  <div className="input-wrap">
                    <Building2 size={18} />
                    <input
                      id="company"
                      name="company"
                      type="text"
                      placeholder="Enter your organization"
                      value={formData.company}
                      onChange={handleChange}
                      autoComplete="organization"
                      required
                    />
                  </div>
                </div>
              </>
            )}

            {!isForgotPassword && (
              <div className="field">
                <label htmlFor="password">Password</label>
                <div className="input-wrap">
                  <LockKeyhole size={18} />
                  <input
                    id="password"
                    name="password"
                    type={showPassword ? "text" : "password"}
                    placeholder={
                      isSignup ? "At least 8 characters" : "Enter your password"
                    }
                    value={formData.password}
                    onChange={handleChange}
                    autoComplete={
                      isSignup ? "new-password" : "current-password"
                    }
                    minLength={isSignup ? 8 : undefined}
                    required
                  />
                  <button
                    type="button"
                    className="eye-button"
                    onClick={() => setShowPassword((visible) => !visible)}
                    aria-label={
                      showPassword ? "Hide password" : "Show password"
                    }
                  >
                    {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                  </button>
                </div>
              </div>
            )}

            {!isSignup && !isForgotPassword && (
              <div className="forgot-password-row">
                <button
                  type="button"
                  className="form-link"
                  onClick={showForgotPassword}
                >
                  Forgot password?
                </button>
              </div>
            )}

            {isSignup && (
              <>
                <div className="field">
                  <label htmlFor="confirmPassword">Confirm password</label>
                  <div className="input-wrap">
                    <LockKeyhole size={18} />
                    <input
                      id="confirmPassword"
                      name="confirmPassword"
                      type={showConfirmPassword ? "text" : "password"}
                      placeholder="Enter your password again"
                      value={formData.confirmPassword}
                      onChange={handleChange}
                      autoComplete="new-password"
                      required
                    />
                    <button
                      type="button"
                      className="eye-button"
                      onClick={() =>
                        setShowConfirmPassword((visible) => !visible)
                      }
                      aria-label={
                        showConfirmPassword ? "Hide password" : "Show password"
                      }
                    >
                      {showConfirmPassword ? (
                        <EyeOff size={18} />
                      ) : (
                        <Eye size={18} />
                      )}
                    </button>
                  </div>
                </div>

                <label className="terms">
                  <input
                    type="checkbox"
                    name="terms"
                    checked={formData.terms}
                    onChange={handleChange}
                  />
                  <span>
                    I agree to the <a href="#terms">Terms of Service</a> and{" "}
                    <a href="#privacy">Privacy Policy</a>.
                  </span>
                </label>
              </>
            )}

            {message && (
              <div
                className={`form-message ${messageType}`}
                role={messageType === "error" ? "alert" : "status"}
                aria-live="polite"
              >
                {message}
              </div>
            )}

            <button className="submit-button" type="submit" disabled={loading}>
              {loading
                ? isSignup
                  ? "Creating account..."
                  : isForgotPassword ? "Requesting reset link..." : "Logging in..."
                : isSignup
                  ? "Create Account"
                  : isForgotPassword
                    ? "Request reset link"
                    : "Log In"}
              {!loading && <ArrowRight size={18} />}
            </button>
          </form>

          <p className="login-prompt">
            {isSignup
              ? "Already have an account? "
              : isForgotPassword
                ? "Remembered your password? "
                : "Don't have an account? "}
            <button
              type="button"
              className="form-link"
              onClick={() => switchPage(isForgotPassword ? false : !isSignup)}
            >
              {isSignup || isForgotPassword ? "Log in" : "Create an account"}
            </button>
          </p>

          <p className="security-note">
            Your information is protected and handled securely.
          </p>
        </section>
        )}
      </main>
    </div>
  );
}

export default App;
