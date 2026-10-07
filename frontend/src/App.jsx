import { useState } from "react";
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

  async function submitRequest(path, payload, fallback) {
    const response = await fetch(`${API_BASE}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || fallback);
    }
    return data;
  }

  async function handleSubmit(event) {
    event.preventDefault();
    setMessage("");
    setMessageType("");

    if (isForgotPassword) {
      setMessage(
        "Password reset is not set up on the server yet. Please contact your TexTech administrator."
      );
      setMessageType("info");
      return;
    }

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

    setLoading(true);
    try {
      if (isSignup) {
        await submitRequest(
          "/api/auth/register",
          {
            full_name: formData.fullName.trim(),
            work_email: formData.email.trim(),
            phone: formData.phone.trim(),
            account_type: accountType,
            organization: formData.company.trim(),
            password: formData.password
          },
          "Registration failed. Please try again."
        );

        setMessage("Your account has been created. You can now log in.");
        setMessageType("success");
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
          "Login failed. Please try again."
        );

        setMessage(`Welcome back, ${data.full_name}.`);
        setMessageType("success");
        setFormData((current) => ({ ...current, password: "" }));
      }
    } catch (error) {
      setMessage(
        error instanceof TypeError
          ? "Could not connect to TexTech's server. Please check that the backend is running."
          : error.message
      );
      setMessageType("error");
    } finally {
      setLoading(false);
    }
  }

  function switchPage(showSignup) {
    setIsSignup(showSignup);
    setIsForgotPassword(false);
    setMessage("");
    setMessageType("");
  }

  function chooseAccountType(value) {
    setAccountType(value);
    setIsSignup(false);
    setIsForgotPassword(false);
    setMessage("");
    setMessageType("");
  }

  function showForgotPassword() {
    setIsForgotPassword(true);
    setMessage("");
    setMessageType("");
  }

  return (
    <div className={`auth-page${isSignup ? " signup-mode" : " login-mode"}`}>
      {!isSignup && (
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

        {!isSignup && (
          <div className="mobile-role-selector">
            <AccountTypeOptions
              accountType={accountType}
              onSelect={chooseAccountType}
            />
          </div>
        )}

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
                  onChange={(event) => setAccountType(event.target.value)}
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
                  : "Logging in..."
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
      </main>
    </div>
  );
}

export default App;
