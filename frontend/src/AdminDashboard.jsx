import { useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  Building2,
  Globe2,
  Layers3,
  LogOut,
  Plus,
  Search,
  Users,
  X,
} from "lucide-react";
import "./AdminDashboard.css";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";
const emptyForm = {
  category: "buying_house",
  company_name: "",
  contact_name: "",
  work_email: "",
  phone: "",
  country: "",
  website: "",
  specialties: "",
  description: "",
};
const categories = [
  ["all", "All profiles"],
  ["buying_house", "Buying houses"],
  ["factory", "Factories"],
  ["foreign_buyer", "Foreign buyers"],
];

function basicAuthHeader(credentials) {
  const bytes = new TextEncoder().encode(`${credentials.username}:${credentials.password}`);
  return `Basic ${btoa(String.fromCharCode(...bytes))}`;
}

function AdminDashboard({ initialCredentials = null, onExit }) {
  const [credentials, setCredentials] = useState(initialCredentials);
  const [login, setLogin] = useState({ username: "", password: "" });
  const [profiles, setProfiles] = useState([]);
  const [registrations, setRegistrations] = useState([]);
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [form, setForm] = useState(emptyForm);
  const [editing, setEditing] = useState(null);
  const [formOpen, setFormOpen] = useState(false);
  const [selected, setSelected] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(Boolean(initialCredentials));

  const authHeader = credentials
    ? basicAuthHeader(credentials)
    : "";

  useEffect(() => {
    if (!initialCredentials) return undefined;
    let active = true;

    async function loadInitialProfiles() {
      try {
        const response = await fetch(`${API_URL}/api/admin/portfolios`, {
          headers: { Authorization: basicAuthHeader(initialCredentials) },
        });
        if (!response.ok) {
          const body = await response.json().catch(() => ({}));
          throw new Error(body.detail || "Could not load profiles");
        }
        const data = await response.json();
        if (active) setProfiles(data);
        const registrationsResponse = await fetch(`${API_URL}/api/admin/registrations`, {
          headers: { Authorization: basicAuthHeader(initialCredentials) },
        });
        if (!registrationsResponse.ok) {
          const body = await registrationsResponse.json().catch(() => ({}));
          throw new Error(body.detail || "Could not load registrations");
        }
        const registrationData = await registrationsResponse.json();
        if (active) setRegistrations(registrationData);
      } catch (requestError) {
        if (active) setError(requestError.message);
      } finally {
        if (active) setLoading(false);
      }
    }

    loadInitialProfiles();
    return () => {
      active = false;
    };
  }, [initialCredentials]);

  async function request(path, options = {}) {
    const response = await fetch(`${API_URL}${path}`, {
      ...options,
      headers: {
        Authorization: authHeader,
        ...(options.body ? { "Content-Type": "application/json" } : {}),
        ...options.headers,
      },
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || `Request failed (${response.status})`);
    }
    return response.status === 204 ? null : response.json();
  }

  async function loadProfiles(activeCredentials = credentials) {
    if (!activeCredentials) return false;
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`${API_URL}/api/admin/portfolios`, {
        headers: {
          Authorization: basicAuthHeader(activeCredentials),
        },
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail || "Could not load profiles");
      }
      setProfiles(await response.json());
      return true;
    } catch (requestError) {
      setError(requestError.message);
      return false;
    } finally {
      setLoading(false);
    }
  }

  async function loadRegistrations(activeCredentials = credentials) {
    if (!activeCredentials) return false;
    try {
      const response = await fetch(`${API_URL}/api/admin/registrations`, {
        headers: { Authorization: basicAuthHeader(activeCredentials) },
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail || "Could not load registrations");
      }
      setRegistrations(await response.json());
      return true;
    } catch (requestError) {
      setError(requestError.message);
      return false;
    }
  }

  const visibleProfiles = useMemo(() => {
    const term = search.trim().toLowerCase();
    return profiles.filter((profile) =>
      (filter === "all" || profile.category === filter)
      && [profile.company_name, profile.contact_name, profile.country, profile.work_email]
        .join(" ")
        .toLowerCase()
        .includes(term),
    );
  }, [filter, profiles, search]);

  async function handleLogin(event) {
    event.preventDefault();
    setError("");
    try {
      const nextCredentials = { ...login };
      const response = await fetch(`${API_URL}/api/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          work_email: nextCredentials.username,
          password: nextCredentials.password,
          account_type: "admin_authority",
        }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail || "Sign-in failed");
      }
      const profilesLoaded = await loadProfiles(nextCredentials);
      const registrationsLoaded = await loadRegistrations(nextCredentials);
      if (profilesLoaded && registrationsLoaded) {
        setCredentials(nextCredentials);
      }
    } catch (requestError) {
      setError(requestError.message || "Could not connect to the TexTech API");
    }
  }

  function startCreate() {
    setEditing(null);
    setForm(emptyForm);
    setFormOpen(true);
    setError("");
  }

  function startEdit(profile) {
    setSelected(null);
    setEditing(profile.id);
    setFormOpen(true);
    setForm(Object.fromEntries(
      Object.keys(emptyForm).map((key) => [key, profile[key] || ""]),
    ));
    setError("");
  }

  async function handleSubmit(event) {
    event.preventDefault();
    setError("");
    try {
      await request(
        editing ? `/api/admin/portfolios/${editing}` : "/api/admin/portfolios",
        {
          method: editing ? "PUT" : "POST",
          body: JSON.stringify(form),
        },
      );
      setEditing(null);
      setFormOpen(false);
      setSelected(null);
      setForm(emptyForm);
      await loadProfiles();
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  async function handleDelete(profile) {
    if (!window.confirm(`Delete ${profile.company_name}'s portfolio?`)) return;
    try {
      await request(`/api/admin/portfolios/${profile.id}`, { method: "DELETE" });
      setSelected(null);
      await loadProfiles();
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  async function handleApprove(registration) {
    setError("");
    try {
      await request(`/api/admin/registrations/${registration.id}/approve`, { method: "POST" });
      await Promise.all([loadProfiles(), loadRegistrations()]);
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  if (!credentials) {
    return (
      <main className="admin-login">
        <form className="admin-login-card" onSubmit={handleLogin}>
          <div className="admin-brand"><Layers3 size={22} /> TEXTECH <span>ADMIN</span></div>
          <p className="admin-kicker">PRIVATE WORKSPACE</p>
          <h1>Welcome back.</h1>
          <p className="admin-muted">Sign in with your verified admin-authority account.</p>
          <label>Work email<input type="email" autoComplete="username" required value={login.username} onChange={(event) => setLogin({ ...login, username: event.target.value })} /></label>
          <label>Password<input type="password" autoComplete="current-password" required value={login.password} onChange={(event) => setLogin({ ...login, password: event.target.value })} /></label>
          {error && <p className="admin-error" role="alert">{error}</p>}
          <button className="admin-primary" type="submit">Sign in</button>
          <a className="admin-back" href="/">Back to registration</a>
        </form>
      </main>
    );
  }

  return (
    <main className="admin-shell">
      <aside className="admin-sidebar">
        <a className="admin-brand" href="/"><Layers3 size={22} /> TEXTECH</a>
        <p className="admin-nav-label">WORKSPACE</p>
        <a className="admin-nav-active" href="/admin"><Building2 size={17} /> Company directory</a>
        <a className="admin-nav" href="/"><ArrowLeft size={17} /> Registration page</a>
        <div className="admin-sidebar-bottom">
          <span>Admin workspace</span>
          <button className="admin-logout" onClick={onExit}><LogOut size={16} /> Sign out</button>
        </div>
      </aside>

      <section className="admin-main">
        <header className="admin-topbar"><span>TexTech / Directory</span><span className="admin-secure">● Secure workspace</span></header>
        <div className="admin-content">
          <div className="admin-title-row">
            <div><p className="admin-kicker">NETWORK MANAGEMENT</p><h1>Company directory</h1><p className="admin-muted">Manage the buying houses, factories and international buyers in your network.</p></div>
            <button className="admin-primary admin-add" onClick={startCreate}><Plus size={17} /> Add profile</button>
          </div>
          <div className="admin-stats">
            <div><span className="admin-stat-icon"><Building2 size={18} /></span><span className="admin-stat-label">Buying houses</span><strong>{profiles.filter((item) => item.category === "buying_house").length}</strong></div>
            <div><span className="admin-stat-icon"><Layers3 size={18} /></span><span className="admin-stat-label">Factories</span><strong>{profiles.filter((item) => item.category === "factory").length}</strong></div>
            <div><span className="admin-stat-icon"><Users size={18} /></span><span className="admin-stat-label">Foreign buyers</span><strong>{profiles.filter((item) => item.category === "foreign_buyer").length}</strong></div>
            <div><span className="admin-stat-icon"><Users size={18} /></span><span className="admin-stat-label">All profiles</span><strong>{profiles.length}</strong></div>
          </div>
          <section className="admin-approvals">
            <div className="admin-directory-head">
              <div><h2>Verified sign-up requests</h2><p>Approve a company after it verifies its email.</p></div>
              <div className="admin-approval-actions">
                <span className="admin-badge">{registrations.length} waiting</span>
                <button
                  className="admin-secondary"
                  type="button"
                  onClick={() => Promise.all([loadProfiles(), loadRegistrations()])}
                >
                  Refresh
                </button>
              </div>
            </div>
            {registrations.length === 0 ? (
              <p className="admin-approval-empty">No verified sign-ups are waiting for approval.</p>
            ) : (
              <div className="admin-table-wrap"><table><thead><tr><th>ORGANIZATION</th><th>CONTACT</th><th>TYPE</th><th>EMAIL</th><th>ACTION</th></tr></thead><tbody>
                {registrations.map((registration) => <tr key={registration.id}><td><strong>{registration.organization}</strong></td><td>{registration.full_name}</td><td>{registration.account_type === "textile_supplier" ? "Factory / supplier" : registration.account_type.replace("_", " ")}</td><td>{registration.work_email}</td><td><button className="admin-primary admin-approve" onClick={() => handleApprove(registration)}>Approve</button></td></tr>)}
              </tbody></table></div>
            )}
          </section>
          <div className="admin-directory">
            <div className="admin-directory-head"><div><h2>Network profiles</h2><p>Add real profiles manually; no sample data is preloaded.</p></div><label className="admin-search"><Search size={16} /><input placeholder="Search companies..." value={search} onChange={(event) => setSearch(event.target.value)} /></label></div>
            <div className="admin-tabs">{categories.map(([value, label]) => <button key={value} className={filter === value ? "selected" : ""} onClick={() => setFilter(value)}>{label}</button>)}</div>
            {error && <p className="admin-error" role="alert">{error}</p>}
            {loading ? <p className="admin-empty">Loading profiles…</p> : visibleProfiles.length === 0 ? <div className="admin-empty"><Building2 size={28} /><strong>No profiles yet</strong><span>Add a real company or buyer to get started.</span><button className="admin-secondary" onClick={startCreate}><Plus size={16} /> Add first profile</button></div> : (
              <div className="admin-table-wrap"><table><thead><tr><th>COMPANY</th><th>TYPE</th><th>LOCATION</th><th>CONTACT</th><th>PORTFOLIO</th></tr></thead><tbody>
                {visibleProfiles.map((profile) => <tr key={profile.id} onClick={() => setSelected(profile)}><td><strong>{profile.company_name}</strong><small>{profile.work_email}</small></td><td><span className="admin-badge">{categories.find(([key]) => key === profile.category)?.[1]?.replace(/s$/, "")}</span></td><td>{profile.country}</td><td>{profile.contact_name}</td><td><button className="admin-view" onClick={(event) => { event.stopPropagation(); setSelected(profile); }}>View portfolio <span>→</span></button></td></tr>)}
              </tbody></table></div>
            )}
          </div>
        </div>
      </section>

      {formOpen && <PortfolioModal form={form} setForm={setForm} editing={editing !== null} onClose={() => { setFormOpen(false); setEditing(null); }} onSubmit={handleSubmit} error={error} />}
      {selected && <div className="admin-overlay" onMouseDown={(event) => { if (event.target === event.currentTarget) setSelected(null); }}><article className="admin-modal admin-profile-modal"><button className="admin-modal-close" onClick={() => setSelected(null)} aria-label="Close"><X size={20} /></button><p className="admin-kicker">{categories.find(([key]) => key === selected.category)?.[1]}</p><h2>{selected.company_name}</h2><p className="admin-muted">{selected.country}</p><div className="admin-profile-grid"><span>Contact</span><strong>{selected.contact_name}</strong><span>Email</span><strong>{selected.work_email}</strong><span>Phone</span><strong>{selected.phone}</strong>{selected.website && <><span>Website</span><strong><a href={selected.website} target="_blank" rel="noreferrer"><Globe2 size={14} /> {selected.website}</a></strong></>}{selected.specialties && <><span>Specialties</span><strong>{selected.specialties}</strong></>}{selected.description && <><span>About</span><strong>{selected.description}</strong></>}</div>{selected.source === "manual" && <div className="admin-modal-actions"><button className="admin-secondary" onClick={() => startEdit(selected)}>Edit profile</button><button className="admin-danger" onClick={() => handleDelete(selected)}>Delete</button></div>}</article></div>}
    </main>
  );
}

function PortfolioModal({ form, setForm, editing, onClose, onSubmit, error }) {
  const fields = [
    ["company_name", "Company name", true],
    ["contact_name", "Contact person", true],
    ["work_email", "Work email", true, "email"],
    ["phone", "Phone number", true, "tel"],
    ["country", "Country", true],
    ["website", "Website", false, "url"],
    ["specialties", "Products / specialties", false],
  ];
  return (
    <div className="admin-overlay" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <form className="admin-modal" onSubmit={onSubmit}>
        <button type="button" className="admin-modal-close" onClick={onClose} aria-label="Close"><X size={20} /></button>
        <p className="admin-kicker">PORTFOLIO DETAILS</p><h2>{editing ? "Edit profile" : "Add a profile"}</h2><p className="admin-muted">Enter the real company details to add them to your directory.</p>
        <label>Profile type<select required value={form.category} onChange={(event) => setForm({ ...form, category: event.target.value })}><option value="buying_house">Buying house</option><option value="factory">Factory / supplier</option><option value="foreign_buyer">Foreign buyer</option></select></label>
        <div className="admin-form-grid">{fields.map(([name, label, required, type = "text"]) => <label key={name}>{label}<input type={type} required={required} value={form[name]} onChange={(event) => setForm({ ...form, [name]: event.target.value })} /></label>)}</div>
        <label>Company overview<textarea rows="3" maxLength="2000" value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} /></label>
        {error && <p className="admin-error" role="alert">{error}</p>}
        <div className="admin-modal-actions"><button type="button" className="admin-secondary" onClick={onClose}>Cancel</button><button className="admin-primary" type="submit">{editing ? "Save changes" : "Create profile"}</button></div>
      </form>
    </div>
  );
}

export default AdminDashboard;
