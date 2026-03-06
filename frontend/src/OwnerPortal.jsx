import { useState, useEffect } from "react";
import {
    registerOwner,
    getMe,
    getMyRestaurants,
    createRestaurant,
    importMenuFromUrl,
    saveImportedMenu,
} from "./api.js";

export default function OwnerPortal({ token, onBack, onTokenUpdate }) {
    const [user, setUser] = useState(null);
    const [myRestaurants, setMyRestaurants] = useState([]);
    const [loading, setLoading] = useState(true);

    // Registration
    const [regEmail, setRegEmail] = useState("");
    const [regPassword, setRegPassword] = useState("");
    const [regError, setRegError] = useState("");

    // Create Restaurant
    const [showCreate, setShowCreate] = useState(false);
    const [restName, setRestName] = useState("");
    const [restCity, setRestCity] = useState("");
    const [restAddress, setRestAddress] = useState("");
    const [restZipcode, setRestZipcode] = useState("");
    const [restPhone, setRestPhone] = useState("");
    const [restLat, setRestLat] = useState("");
    const [restLng, setRestLng] = useState("");
    const [restDesc, setRestDesc] = useState("");

    // Menu Import
    const [importUrl, setImportUrl] = useState("");
    const [importLoading, setImportLoading] = useState(false);
    const [importedMenu, setImportedMenu] = useState(null);
    const [importError, setImportError] = useState("");
    const [importRestId, setImportRestId] = useState(null);
    const [saveStatus, setSaveStatus] = useState("");

    useEffect(() => {
        if (token) loadProfile();
    }, [token]);

    async function loadProfile() {
        setLoading(true);
        try {
            const me = await getMe(token);
            setUser(me);
            if (me.role === "owner" || me.role === "admin") {
                const rests = await getMyRestaurants(token);
                setMyRestaurants(rests);
            }
        } catch {
            setUser(null);
        }
        setLoading(false);
    }

    async function handleRegisterOwner(e) {
        e.preventDefault();
        setRegError("");
        try {
            const data = await registerOwner({ email: regEmail, password: regPassword });
            localStorage.setItem("token", data.access_token);
            onTokenUpdate(data.access_token);
            setRegEmail("");
            setRegPassword("");
        } catch (err) {
            setRegError(err.message || "Registration failed");
        }
    }

    async function handleCreateRestaurant(e) {
        e.preventDefault();
        try {
            await createRestaurant(token, {
                name: restName,
                city: restCity,
                address: restAddress,
                zipcode: restZipcode,
                phone: restPhone,
                latitude: parseFloat(restLat) || 0,
                longitude: parseFloat(restLng) || 0,
                description: restDesc,
            });
            setShowCreate(false);
            setRestName(""); setRestCity(""); setRestAddress(""); setRestZipcode("");
            setRestPhone(""); setRestLat(""); setRestLng(""); setRestDesc("");
            loadProfile();
        } catch (err) {
            alert(err.message || "Failed to create restaurant");
        }
    }

    async function handleImportMenu() {
        if (!importUrl.trim()) return;
        setImportLoading(true);
        setImportError("");
        setImportedMenu(null);
        setSaveStatus("");
        try {
            const data = await importMenuFromUrl(token, importUrl.trim());
            if (data.error) {
                setImportError(data.error);
            } else {
                setImportedMenu(data);
            }
        } catch (err) {
            setImportError(err.message || "Import failed");
        }
        setImportLoading(false);
    }

    async function handleSaveMenu() {
        if (!importRestId || !importedMenu) return;
        setSaveStatus("saving");
        try {
            const result = await saveImportedMenu(token, importRestId, importedMenu);
            setSaveStatus(`Saved! ${result.created.categories} categories, ${result.created.items} items imported.`);
            setImportedMenu(null);
            setImportUrl("");
            loadProfile();
        } catch (err) {
            setSaveStatus("Error: " + (err.message || "Failed to save"));
        }
    }

    if (loading) {
        return (
            <div className="owner-portal">
                <div className="owner-loading">Loading...</div>
            </div>
        );
    }

    // Not logged in or not an owner — show register
    if (!user || (user.role !== "owner" && user.role !== "admin")) {
        return (
            <div className="owner-portal">
                <button className="owner-back-btn" onClick={onBack}>← Back to App</button>
                <div className="owner-card owner-register">
                    <h2>🍽️ Restaurant Owner Portal</h2>
                    <p className="owner-subtitle">Register as a restaurant owner to manage your menu</p>
                    {user && (
                        <div className="owner-notice">
                            You're logged in as <strong>{user.email}</strong> (customer).
                            Register below to upgrade to owner.
                        </div>
                    )}
                    <form onSubmit={handleRegisterOwner}>
                        <label>
                            Email
                            <input type="email" value={regEmail} onChange={(e) => setRegEmail(e.target.value)} required />
                        </label>
                        <label>
                            Password
                            <input type="password" value={regPassword} onChange={(e) => setRegPassword(e.target.value)} required minLength={6} />
                        </label>
                        {regError && <div className="owner-error">{regError}</div>}
                        <button type="submit">Register as Owner</button>
                    </form>
                </div>
            </div>
        );
    }

    // Owner dashboard
    return (
        <div className="owner-portal">
            <div className="owner-header">
                <button className="owner-back-btn" onClick={onBack}>← Back to App</button>
                <h2>🍽️ Owner Dashboard</h2>
                <span className="owner-email">{user.email}</span>
            </div>

            {/* My Restaurants */}
            <div className="owner-card">
                <div className="owner-card-header">
                    <h3>My Restaurants ({myRestaurants.length})</h3>
                    <button className="owner-add-btn" onClick={() => setShowCreate(!showCreate)}>
                        {showCreate ? "✕ Cancel" : "+ Add Restaurant"}
                    </button>
                </div>

                {showCreate && (
                    <form className="owner-form" onSubmit={handleCreateRestaurant}>
                        <div className="owner-form-grid">
                            <label>
                                Restaurant Name *
                                <input value={restName} onChange={(e) => setRestName(e.target.value)} required placeholder="e.g. Joe's Pizza" />
                            </label>
                            <label>
                                City *
                                <input value={restCity} onChange={(e) => setRestCity(e.target.value)} required placeholder="e.g. Lancaster" />
                            </label>
                            <label>
                                Address
                                <input value={restAddress} onChange={(e) => setRestAddress(e.target.value)} placeholder="123 Main St" />
                            </label>
                            <label>
                                Zipcode
                                <input value={restZipcode} onChange={(e) => setRestZipcode(e.target.value)} placeholder="29720" />
                            </label>
                            <label>
                                Phone
                                <input value={restPhone} onChange={(e) => setRestPhone(e.target.value)} placeholder="803-555-1234" />
                            </label>
                            <label>
                                Description
                                <input value={restDesc} onChange={(e) => setRestDesc(e.target.value)} placeholder="Best pizza in town" />
                            </label>
                            <label>
                                Latitude
                                <input value={restLat} onChange={(e) => setRestLat(e.target.value)} placeholder="34.720" />
                            </label>
                            <label>
                                Longitude
                                <input value={restLng} onChange={(e) => setRestLng(e.target.value)} placeholder="-80.771" />
                            </label>
                        </div>
                        <button type="submit" className="owner-primary-btn">Create Restaurant</button>
                    </form>
                )}

                {myRestaurants.length === 0 && !showCreate && (
                    <p className="owner-empty">No restaurants yet. Click "+ Add Restaurant" to get started.</p>
                )}

                <div className="owner-restaurants-list">
                    {myRestaurants.map((r) => (
                        <div key={r.id} className="owner-restaurant-item">
                            <div className="owner-restaurant-info">
                                <strong>{r.name}</strong>
                                <span className="owner-restaurant-meta">
                                    {r.city} · #{r.slug}
                                </span>
                            </div>
                            <button
                                className="owner-import-trigger"
                                onClick={() => {
                                    setImportRestId(r.id);
                                    setImportedMenu(null);
                                    setImportUrl("");
                                    setImportError("");
                                    setSaveStatus("");
                                }}
                            >
                                🤖 Import Menu
                            </button>
                        </div>
                    ))}
                </div>
            </div>

            {/* Menu Import */}
            {importRestId && (
                <div className="owner-card owner-import-card">
                    <h3>
                        🤖 AI Menu Import
                        <span className="owner-import-for">
                            for {myRestaurants.find((r) => r.id === importRestId)?.name}
                        </span>
                    </h3>
                    <p className="owner-subtitle">
                        Paste the restaurant's website/menu URL and our AI will extract the full menu automatically.
                    </p>

                    <div className="owner-import-input">
                        <input
                            type="url"
                            value={importUrl}
                            onChange={(e) => setImportUrl(e.target.value)}
                            placeholder="https://www.restaurant.com/menu"
                            disabled={importLoading}
                        />
                        <button
                            onClick={handleImportMenu}
                            disabled={importLoading || !importUrl.trim()}
                            className="owner-primary-btn"
                        >
                            {importLoading ? (
                                <span className="owner-spinner">⏳ Extracting...</span>
                            ) : (
                                "🔍 Extract Menu"
                            )}
                        </button>
                    </div>

                    {importLoading && (
                        <div className="owner-import-progress">
                            <div className="owner-progress-bar">
                                <div className="owner-progress-fill"></div>
                            </div>
                            <p>Scraping website and extracting menu with AI... This may take 15-30 seconds.</p>
                        </div>
                    )}

                    {importError && (
                        <div className="owner-error">❌ {importError}</div>
                    )}

                    {/* Menu Preview */}
                    {importedMenu && (
                        <div className="owner-menu-preview">
                            <div className="owner-menu-header">
                                <h4>✅ Extracted: {importedMenu.restaurant_name}</h4>
                                <span className="owner-menu-stats">
                                    {importedMenu.categories?.length || 0} categories ·{" "}
                                    {importedMenu.categories?.reduce((s, c) => s + (c.items?.length || 0), 0) || 0} items
                                </span>
                            </div>

                            {importedMenu.categories?.map((cat, ci) => (
                                <div key={ci} className="owner-preview-category">
                                    <h5>{cat.name} <span className="owner-cat-count">{cat.items?.length || 0}</span></h5>
                                    <div className="owner-preview-items">
                                        {cat.items?.map((item, ii) => (
                                            <div key={ii} className="owner-preview-item">
                                                <div className="owner-preview-item-info">
                                                    <span className="owner-preview-item-name">{item.name}</span>
                                                    {item.description && (
                                                        <span className="owner-preview-item-desc">{item.description}</span>
                                                    )}
                                                </div>
                                                <span className="owner-preview-item-price">
                                                    {item.price_cents > 0
                                                        ? `$${(item.price_cents / 100).toFixed(2)}`
                                                        : "—"}
                                                </span>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            ))}

                            <div className="owner-save-section">
                                <button onClick={handleSaveMenu} className="owner-save-btn">
                                    💾 Save Menu to Database
                                </button>
                                <button onClick={() => setImportedMenu(null)} className="owner-discard-btn">
                                    Discard
                                </button>
                            </div>
                        </div>
                    )}

                    {saveStatus && (
                        <div className={`owner-save-status ${saveStatus.startsWith("Error") ? "error" : "success"}`}>
                            {saveStatus}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}
