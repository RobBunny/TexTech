
import { useState } from "react";
import {
  Eye,
  EyeOff,
  Mail,
  LockKeyhole,
  UserRound,
  Phone,
  Building2,
  ArrowRight,
  CheckCircle2,
  Layers3
} from "lucide-react";
import "./App.css";

function App() {
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [role, setRole] = useState("buying_house");
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

  function handleChange(event) {
    const { name, value, type, checked } = event.target;

    setFormData({
      ...formData,
      [name]: type === "checkbox" ? checked : value
    });
  }

  async function handleSubmit(event) {
    event.preventDefault();
    setMessage("");
    setMessageType("");

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

    if (!["buying_house", "factory"].includes(role)) {
      setMessage(
        "Staff accounts require authorization. Please contact TexTech."
      );
      setMessageType("error");
      return;
    }

    setLoading(true);

    try {
      const response = await fetch(
        "http://127.0.0.1:8000/api/auth/register",
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json"
          },
          body: JSON.stringify({
            full_name: formData.fullName.trim(),
            work_email: formData.email.trim(),
            phone: formData.phone.trim(),
            account_type: role,
            organization: formData.company.trim(),
            password: formData.password
          })
        }
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          data.detail || "Registration failed. Please try again."
        );
      }

      setMessage(
        "Registration successful! Email verification will be available soon."
      );
      setMessageType("success");

      setFormData({
        fullName: "",
        email: "",
        phone: "",
        company: "",
        password: "",
        confirmPassword: "",
        terms: false
      });
      setRole("buying_house");
    } catch (error) {
      if (error instanceof TypeError) {
        setMessage(
          "Could not connect to TexTech's server. Please check that the backend is running."
        );
      } else {
        setMessage(error.message);
      }

      setMessageType("error");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="signup-page">
      <aside className="showcase">
        <div className="brand">
          <div className="brand-icon">
            <Layers3 size={25} />
          </div>
          <span>
            TEX<span className="brand-light">TECH</span>
          </span>
        </div>

        <div className="showcase-content">
          <span className="eyebrow">THE FUTURE OF FABRIC SOURCING</span>

          <h1>
            Better fabrics.
            <br />
            Better connections.
          </h1>

          <p>
            Discover suppliers, compare textiles, and bring your next
            collection to life through one connected marketplace.
          </p>

          <div className="benefit">
            <CheckCircle2 size={19} />
            <span>Connect with verified textile suppliers</span>
          </div>

          <div className="benefit">
            <CheckCircle2 size={19} />
            <span>Compare fabrics and wholesale prices</span>
          </div>

          <div className="benefit">
            <CheckCircle2 size={19} />
            <span>Discover fabrics for every season</span>
          </div>
        </div>

        <div className="showcase-footer">
          A smarter way to source textiles.
        </div>
      </aside>

      <main className="signup-area">
        <div className="mobile-brand">
          <Layers3 size={24} />
          <span>TEXTECH</span>
        </div>

        <div className="signup-card">
          <div className="form-heading">
            <span className="eyebrow">CREATE YOUR ACCOUNT</span>
            <h2>Join the network.</h2>
            <p>
              Get started with your professional fabric sourcing account.
            </p>
          </div>

          <form onSubmit={handleSubmit}>
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

            <div className="field">
              <label htmlFor="email">Work email address</label>
              <div className="input-wrap">
                <Mail size={18} />
                <input
                  id="email"
                  name="email"
                  type="email"
                  placeholder="you@company.com"
                  value={formData.email}
                  onChange={handleChange}
                  autoComplete="email"
                  required
                />
              </div>
            </div>

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
              <label htmlFor="role">Account type</label>
              <select
                id="role"
                value={role}
                onChange={(event) => setRole(event.target.value)}
              >
                <option value="buying_house">Buying House</option>
                <option value="factory">Factory / Supplier</option>
                <option value="staff">Staff / Employee</option>
              </select>
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

            <div className="field">
              <label htmlFor="password">Password</label>
              <div className="input-wrap">
                <LockKeyhole size={18} />
                <input
                  id="password"
                  name="password"
                  type={showPassword ? "text" : "password"}
                  placeholder="At least 8 characters"
                  value={formData.password}
                  onChange={handleChange}
                  autoComplete="new-password"
                  minLength={8}
                  required
                />
                <button
                  type="button"
                  className="eye-button"
                  onClick={() => setShowPassword(!showPassword)}
                  aria-label={showPassword ? "Hide password" : "Show password"}
                >
                  {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>
            </div>

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
                    setShowConfirmPassword(!showConfirmPassword)
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

            {message && (
              <div
                className={`form-message ${messageType}`}
                role="status"
                aria-live="polite"
              >
                {message}
              </div>
            )}

            <button
              className="submit-button"
              type="submit"
              disabled={loading}
            >
              {loading ? "Creating account..." : "Create Account"}
              {!loading && <ArrowRight size={18} />}
            </button>
          </form>

          <p className="login-prompt">
            Already have an account? <a href="/login">Log in</a>
          </p>

          <p className="security-note">
            Your business information should be kept secure.
          </p>
        </div>
      </main>
    </div>
  );
}

export default App;