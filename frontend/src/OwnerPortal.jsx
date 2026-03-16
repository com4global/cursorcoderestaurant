import { useState, useEffect, useRef, useCallback } from "react";
import {
    registerOwner,
    getMe,
    getMyRestaurants,
    createRestaurant,
    importMenuFromUrl,
    extractMenuFromFile,
    saveImportedMenu,
    fetchOrders,
    fetchArchivedOrders,
    fetchComplaints,
    updateOrderStatus,
    updateNotifications,
    startOwnerTrial,
    createOwnerSubscription,
    getOwnerSubscription,
    getManageBillingUrl,
} from "./api.js";
import SalesAnalytics from "./SalesAnalytics.jsx";

export default function OwnerPortal({ token, onBack, onTokenUpdate }) {
    const [user, setUser] = useState(null);
    const [myRestaurants, setMyRestaurants] = useState([]);
    const [loading, setLoading] = useState(true);

    // Subscription
    const [subscription, setSubscription] = useState(null); // { plan, status, active, trial_end, ... }
    const [subLoading, setSubLoading] = useState(false);

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
    const [saveError, setSaveError] = useState("");
    const [extractMode, setExtractMode] = useState(null); // "url" | "image" | null
    const [dragActive, setDragActive] = useState(false);

    // Orders Dashboard
    const [activeTab, setActiveTab] = useState({}); // { restaurantId: "orders" | "menu" | "settings" }
    const [orders, setOrders] = useState({}); // { restaurantId: [...orders] }
    const [ordersLoading, setOrdersLoading] = useState({});
    const [lastOrderCounts, setLastOrderCounts] = useState({});
    const audioRef = useRef(null);

    // Archived orders
    const [ordersView, setOrdersView] = useState({}); // { restaurantId: "active" | "archived" }
    const [archivedOrders, setArchivedOrders] = useState({}); // { restaurantId: { orders, total, page, total_pages } }
    const [archivedLoading, setArchivedLoading] = useState({});
    // Customer complaints (escalated feedback)
    const [complaints, setComplaints] = useState({}); // { restaurantId: [...] }

    // Search & date filters
    const [orderSearch, setOrderSearch] = useState({}); // { restaurantId: "search text" }
    const [orderDateFrom, setOrderDateFrom] = useState({}); // { restaurantId: "2026-03-01" }
    const [orderDateTo, setOrderDateTo] = useState({}); // { restaurantId: "2026-03-10" }
    const searchTimerRef = useRef({});

    // Notification settings
    const [notifEmail, setNotifEmail] = useState({});
    const [notifPhone, setNotifPhone] = useState({});
    const [notifSaving, setNotifSaving] = useState({});

    useEffect(() => {
        if (token) {
            loadProfile();
        } else {
            setLoading(false);
        }
    }, [token]);

    // --- Orders polling ---
    const loadOrders = useCallback(async (restaurantId, filters) => {
        if (!token) return;
        setOrdersLoading((p) => ({ ...p, [restaurantId]: true }));
        try {
            const data = await fetchOrders(token, restaurantId, filters || {});
            const prevCount = lastOrderCounts[restaurantId] || 0;
            const confirmedOrders = data.filter((o) => o.status === "confirmed");
            // Play sound if new confirmed orders appeared
            if (confirmedOrders.length > prevCount && prevCount > 0) {
                playNotificationSound();
            }
            setLastOrderCounts((p) => ({ ...p, [restaurantId]: confirmedOrders.length }));
            setOrders((p) => ({ ...p, [restaurantId]: data }));
        } catch {
            // silent
        }
        setOrdersLoading((p) => ({ ...p, [restaurantId]: false }));
    }, [token, lastOrderCounts]);

    // --- Load archived orders ---
    const loadArchivedOrders = useCallback(async (restaurantId, page = 1, filters) => {
        if (!token) return;
        setArchivedLoading((p) => ({ ...p, [restaurantId]: true }));
        try {
            const data = await fetchArchivedOrders(token, restaurantId, page, filters || {});
            setArchivedOrders((p) => ({ ...p, [restaurantId]: data }));
        } catch {
            // silent
        }
        setArchivedLoading((p) => ({ ...p, [restaurantId]: false }));
    }, [token]);

    // Poll orders for restaurants with "orders" tab active
    useEffect(() => {
        const intervals = [];
        for (const rId of Object.keys(activeTab)) {
            if (activeTab[rId] === "orders") {
                const filters = {
                    search: orderSearch[rId] || undefined,
                    dateFrom: orderDateFrom[rId] || undefined,
                    dateTo: orderDateTo[rId] || undefined,
                };
                loadOrders(parseInt(rId), filters);
                const iv = setInterval(() => loadOrders(parseInt(rId), filters), 10000);
                intervals.push(iv);
            }
        }
        return () => intervals.forEach(clearInterval);
    }, [activeTab, token, orderSearch, orderDateFrom, orderDateTo]);

    // --- Debounced search handler ---
    function handleOrderSearch(rId, value) {
        setOrderSearch((p) => ({ ...p, [rId]: value }));
        // Clear existing timer
        if (searchTimerRef.current[rId]) clearTimeout(searchTimerRef.current[rId]);
        // Debounce: reload after 500ms of no typing
        searchTimerRef.current[rId] = setTimeout(() => {
            const filters = { search: value || undefined, dateFrom: orderDateFrom[rId] || undefined, dateTo: orderDateTo[rId] || undefined };
            const view = ordersView[rId] || "active";
            if (view === "active") {
                loadOrders(rId, filters);
            } else {
                loadArchivedOrders(rId, 1, filters);
            }
        }, 500);
    }

    // --- Date filter handler ---
    function handleDateFilter(rId, field, value) {
        if (field === "from") setOrderDateFrom((p) => ({ ...p, [rId]: value }));
        else setOrderDateTo((p) => ({ ...p, [rId]: value }));
        const filters = {
            search: orderSearch[rId] || undefined,
            dateFrom: field === "from" ? (value || undefined) : (orderDateFrom[rId] || undefined),
            dateTo: field === "to" ? (value || undefined) : (orderDateTo[rId] || undefined),
        };
        const view = ordersView[rId] || "active";
        if (view === "active") {
            loadOrders(rId, filters);
        } else {
            loadArchivedOrders(rId, 1, filters);
        }
    }

    // --- Clear all filters ---
    function clearOrderFilters(rId) {
        setOrderSearch((p) => ({ ...p, [rId]: "" }));
        setOrderDateFrom((p) => ({ ...p, [rId]: "" }));
        setOrderDateTo((p) => ({ ...p, [rId]: "" }));
        const view = ordersView[rId] || "active";
        if (view === "active") {
            loadOrders(rId, {});
        } else {
            loadArchivedOrders(rId, 1, {});
        }
    }

    function playNotificationSound() {
        try {
            const ctx = new (window.AudioContext || window.webkitAudioContext)();
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.frequency.value = 800;
            gain.gain.value = 0.3;
            osc.start();
            osc.stop(ctx.currentTime + 0.3);
            setTimeout(() => {
                const osc2 = ctx.createOscillator();
                osc2.connect(gain);
                osc2.frequency.value = 1000;
                osc2.start();
                osc2.stop(ctx.currentTime + 0.3);
            }, 200);
        } catch {
            // AudioContext not available
        }
    }

    async function loadProfile() {
        setLoading(true);
        try {
            const me = await getMe(token);
            setUser(me);
            if (me.role === "owner" || me.role === "admin") {
                // Load subscription status
                try {
                    const sub = await getOwnerSubscription(token);
                    setSubscription(sub);
                } catch { setSubscription(null); }

                const rests = await getMyRestaurants(token);
                setMyRestaurants(rests);
                // Initialize notification fields
                const ne = {}, np = {};
                rests.forEach((r) => {
                    ne[r.id] = r.notification_email || "";
                    np[r.id] = r.notification_phone || "";
                });
                setNotifEmail(ne);
                setNotifPhone(np);
            }
        } catch {
            setUser(null);
        }
        setLoading(false);
    }

    async function handleStartTrial() {
        setSubLoading(true);
        try {
            const res = await startOwnerTrial(token);
            setSubscription({ plan: res.plan, status: res.status, active: true, trial_end: res.trial_end });
        } catch (err) {
            alert(err.message || "Failed to start trial");
        }
        setSubLoading(false);
    }

    async function handleSubscribe(plan) {
        setSubLoading(true);
        try {
            const res = await createOwnerSubscription(token, plan);
            if (res.checkout_url) {
                // If dev-mode (simulated), just refresh subscription
                if (res.session_id === "sim_dev") {
                    const sub = await getOwnerSubscription(token);
                    setSubscription(sub);
                } else {
                    window.location.href = res.checkout_url;
                }
            }
        } catch (err) {
            alert(err.message || "Failed to create subscription");
        }
        setSubLoading(false);
    }

    async function handleManageBilling() {
        try {
            const res = await getManageBillingUrl(token);
            if (res.url) window.location.href = res.url;
        } catch (err) {
            alert(err.message || "Billing portal unavailable");
        }
    }

    async function handleRegisterOwner(e) {
        e.preventDefault();
        setRegError("");
        try {
            const data = await registerOwner({ email: regEmail, password: regPassword });
            if (onTokenUpdate) onTokenUpdate(data.access_token);
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
                latitude: restLat ? parseFloat(restLat) : undefined,
                longitude: restLng ? parseFloat(restLng) : undefined,
                description: restDesc,
            });
            setRestName(""); setRestCity(""); setRestAddress(""); setRestZipcode("");
            setRestPhone(""); setRestLat(""); setRestLng(""); setRestDesc("");
            setShowCreate(false);
            loadProfile();
        } catch {
            alert("Failed to create restaurant");
        }
    }

    async function handleImportMenu() {
        if (!importUrl.trim()) return;
        setImportLoading(true);
        setImportError("");
        setImportedMenu(null);
        try {
            const data = await importMenuFromUrl(token, importUrl.trim());
            if (data.error) {
                setImportError(data.error);
            } else {
                // Convert price_cents to price (dollars) and strip empty categories
                if (data.categories) {
                    data.categories = data.categories
                        .filter(c => c.items && c.items.length > 0)
                        .map(c => ({
                            ...c,
                            items: c.items.map(item => ({
                                ...item,
                                // Always prefer price_cents (from AI), convert to dollars
                                price: item.price_cents ? (item.price_cents / 100) : (item.price || 0),
                            }))
                        }));
                }
                setImportedMenu(data);
            }
        } catch (err) {
            setImportError(err.message || "Import failed");
        }
        setImportLoading(false);
    }

    async function handleSaveMenu() {
        if (!importedMenu || !importRestId) return;
        setSaveStatus("saving");
        setSaveError("");
        try {
            await saveImportedMenu(token, importRestId, importedMenu);
            setSaveStatus("saved");
            setSaveError("");
            loadProfile();
        } catch (err) {
            setSaveStatus("error");
            setSaveError(err?.message || "Failed to save. Try again.");
        }
    }

    // --- Editable menu helpers ---
    function updateItem(catIndex, itemIndex, field, value) {
        setImportedMenu((prev) => {
            const copy = JSON.parse(JSON.stringify(prev));
            if (field === "price") {
                copy.categories[catIndex].items[itemIndex].price = parseFloat(value) || 0;
            } else {
                copy.categories[catIndex].items[itemIndex][field] = value;
            }
            return copy;
        });
    }

    function deleteItem(catIndex, itemIndex) {
        setImportedMenu((prev) => {
            const copy = JSON.parse(JSON.stringify(prev));
            copy.categories[catIndex].items.splice(itemIndex, 1);
            return copy;
        });
    }

    function updateCategoryName(catIndex, newName) {
        setImportedMenu((prev) => {
            const copy = JSON.parse(JSON.stringify(prev));
            copy.categories[catIndex].name = newName;
            return copy;
        });
    }

    function addItem(catIndex) {
        setImportedMenu((prev) => {
            const copy = JSON.parse(JSON.stringify(prev));
            copy.categories[catIndex].items.push({ name: "", description: "", price: 0 });
            return copy;
        });
    }

    function addCategory() {
        setImportedMenu((prev) => {
            const copy = JSON.parse(JSON.stringify(prev));
            copy.categories.push({ name: "New Category", items: [{ name: "", description: "", price: 0 }] });
            return copy;
        });
    }

    // --- Compress image to fit within server limits ---
    async function compressImage(file, maxSizeMB = 2) {
        const imageExts = [".jpg", ".jpeg", ".png", ".webp"];
        const ext = "." + file.name.split(".").pop().toLowerCase();
        if (!imageExts.includes(ext)) return file; // skip non-images
        if (file.size <= maxSizeMB * 1024 * 1024) return file; // already small enough

        return new Promise((resolve) => {
            const reader = new FileReader();
            reader.onload = (e) => {
                const img = new Image();
                img.onload = () => {
                    const canvas = document.createElement("canvas");
                    // Scale down large images — cap at 2000px on longest side
                    let { width, height } = img;
                    const maxDim = 2000;
                    if (width > maxDim || height > maxDim) {
                        const ratio = Math.min(maxDim / width, maxDim / height);
                        width = Math.round(width * ratio);
                        height = Math.round(height * ratio);
                    }
                    canvas.width = width;
                    canvas.height = height;
                    const ctx = canvas.getContext("2d");
                    ctx.drawImage(img, 0, 0, width, height);
                    canvas.toBlob(
                        (blob) => {
                            if (blob) {
                                const compressed = new File([blob], file.name, { type: "image/jpeg" });
                                console.log(`[Extract] Compressed ${(file.size / 1024 / 1024).toFixed(1)}MB → ${(compressed.size / 1024 / 1024).toFixed(1)}MB`);
                                resolve(compressed);
                            } else {
                                resolve(file);
                            }
                        },
                        "image/jpeg",
                        0.8
                    );
                };
                img.onerror = () => resolve(file);
                img.src = e.target.result;
            };
            reader.onerror = () => resolve(file);
            reader.readAsDataURL(file);
        });
    }

    // --- Extract from image file ---
    async function handleExtractFromFile(file, restaurantId) {
        if (!file) return;
        const restId = restaurantId || importRestId;
        if (!restId) {
            setImportError("No restaurant selected. Please go back and select a restaurant.");
            return;
        }
        const allowed = [".jpg", ".jpeg", ".png", ".webp", ".pdf", ".docx", ".doc", ".xlsx", ".xls"];
        const ext = "." + file.name.split(".").pop().toLowerCase();
        if (!allowed.includes(ext)) {
            setImportError("Unsupported file type. Use JPG, PNG, WebP, PDF, DOCX, or XLSX.");
            return;
        }
        if (file.size > 20 * 1024 * 1024) {
            setImportError("File too large. Max 20MB.");
            return;
        }
        setImportLoading(true);
        setImportError("");
        setImportedMenu(null);
        try {
            // Compress large images to avoid server body size limits
            const uploadFile = await compressImage(file);
            console.log(`[Extract] Uploading ${uploadFile.name} (${(uploadFile.size / 1024).toFixed(0)}KB) to restaurant ${restId}`);
            const data = await extractMenuFromFile(token, restId, uploadFile);
            console.log("[Extract] Response:", data);
            if (data.error) {
                setImportError(data.error);
                setImportLoading(false);
                return;
            }
            if (data.categories) {
                data.categories = data.categories
                    .filter(c => c.items && c.items.length > 0)
                    .map(c => ({
                        ...c,
                        items: c.items.map(item => ({
                            ...item,
                            price: item.price_cents ? (item.price_cents / 100) : (item.price || 0),
                        }))
                    }));
            }
            if (!data.categories || data.categories.length === 0) {
                setImportError("No menu items found in the image. Try a clearer or higher-resolution photo.");
                setImportLoading(false);
                return;
            }
            setImportedMenu(data);
        } catch (err) {
            console.error("[Extract] Upload failed:", err);
            const msg = err.message || "";
            if (msg.includes("Failed to fetch") || msg.includes("NetworkError") || msg.includes("Load failed")) {
                setImportError("Network error — could not reach the server. Check your connection and try again.");
            } else if (msg.includes("413") || msg.includes("too large") || msg.includes("payload")) {
                setImportError("Image too large for the server. Try a smaller or lower-resolution photo.");
            } else {
                setImportError(msg || "Extraction failed. Try a clearer photo.");
            }
        }
        setImportLoading(false);
    }

    // --- Order status update ---
    async function handleStatusChange(restaurantId, orderId, newStatus) {
        try {
            await updateOrderStatus(token, orderId, newStatus);
            loadOrders(restaurantId);
        } catch {
            alert("Failed to update order status");
        }
    }

    // --- Save notification settings ---
    async function handleSaveNotifications(restaurantId) {
        setNotifSaving((p) => ({ ...p, [restaurantId]: true }));
        try {
            await updateNotifications(token, restaurantId, {
                notification_email: notifEmail[restaurantId] || "",
                notification_phone: notifPhone[restaurantId] || "",
            });
        } catch {
            alert("Failed to save notification settings");
        }
        setNotifSaving((p) => ({ ...p, [restaurantId]: false }));
    }

    // --- Status badge ---
    function StatusBadge({ status }) {
        const colors = {
            pending: { bg: "#fef3c7", color: "#92400e", label: "🛒 In Cart" },
            confirmed: { bg: "#fde68a", color: "#92400e", label: "🔔 New Order" },
            accepted: { bg: "#d1fae5", color: "#065f46", label: "✅ Accepted" },
            preparing: { bg: "#dbeafe", color: "#1e40af", label: "🍳 Preparing" },
            ready: { bg: "#a7f3d0", color: "#065f46", label: "📦 Ready" },
            rejected: { bg: "#fee2e2", color: "#991b1b", label: "❌ Rejected" },
            completed: { bg: "#e5e7eb", color: "#374151", label: "✓ Done" },
        };
        const s = colors[status] || { bg: "#e5e7eb", color: "#374151", label: status };
        return (
            <span style={{
                background: s.bg, color: s.color, padding: "3px 10px", borderRadius: 12,
                fontSize: "0.78rem", fontWeight: 700, whiteSpace: "nowrap",
            }}>{s.label}</span>
        );
    }

    // --- Tab helper ---
    function getTab(rId) { return activeTab[rId] || "menu"; }
    function setTab(rId, tab) {
        setActiveTab((p) => ({ ...p, [rId]: tab }));
        if (tab === "orders") {
            if (!orders[rId]) loadOrders(rId, {});
            fetchComplaints(token, rId).then((list) => setComplaints((p) => ({ ...p, [rId]: list || [] }))).catch(() => {});
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
                <div className="owner-card owner-register">
                    <h2>🍽️ Restaurant Owner Portal</h2>
                    <p>Register as a restaurant owner to manage your menus and receive orders.</p>
                    <form onSubmit={handleRegisterOwner}>
                        <label>Email<input type="email" value={regEmail} onChange={(e) => setRegEmail(e.target.value)} required /></label>
                        <label>Password<input type="password" value={regPassword} onChange={(e) => setRegPassword(e.target.value)} required minLength={6} /></label>
                        {regError && <p className="owner-error">{regError}</p>}
                        <button type="submit" className="owner-primary-btn">Continue as Owner</button>
                    </form>
                </div>
            </div>
        );
    }

    // Subscription required — show pricing page
    if (!subscription || !subscription.active) {
        return (
            <div className="owner-portal">
                <div className="owner-header">
                    <h2>🍽️ Choose Your Plan</h2>
                    <button className="owner-back-btn" onClick={onBack}>← Back</button>
                </div>
                {subscription && subscription.trial_expired && (
                    <div style={{
                        background: 'linear-gradient(135deg, #7f1d1d, #991b1b)', border: '1px solid #ef4444',
                        borderRadius: 12, padding: '1rem 1.5rem', margin: '0 1rem 1.5rem', textAlign: 'center'
                    }}>
                        <div style={{ fontSize: '1.3rem', marginBottom: 4 }}>⏰ Your Free Trial Has Expired</div>
                        <div style={{ color: '#fca5a5', fontSize: '0.9rem' }}>
                            Your 30-day trial ended. Upgrade to continue using the Owner Dashboard.
                        </div>
                    </div>
                )}
                {(!subscription || !subscription.trial_expired) && (
                    <p style={{ textAlign: 'center', color: '#aaa', margin: '0.5rem 0 1.5rem', fontSize: '1rem' }}>
                        Power your restaurant with AI-driven ordering, analytics, and more.
                    </p>
                )}
                <div style={{
                    display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
                    gap: '1.25rem', padding: '0 1rem', maxWidth: 960, margin: '0 auto'
                }}>
                    {/* Free Trial */}
                    <div style={{
                        background: 'linear-gradient(145deg, #1a1a2e, #16213e)', borderRadius: 16, padding: '2rem 1.5rem',
                        border: '1px solid #333', display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center'
                    }}>
                        <div style={{ fontSize: '2.5rem', marginBottom: 8 }}>🆓</div>
                        <h3 style={{ color: '#fff', margin: '0.5rem 0', fontSize: '1.3rem' }}>Free Trial</h3>
                        <div style={{ fontSize: '2rem', fontWeight: 800, color: '#4ade80', marginBottom: 4 }}>$0</div>
                        <div style={{ color: '#888', fontSize: '0.85rem', marginBottom: 16 }}>for 1 month</div>
                        <ul style={{ color: '#ccc', fontSize: '0.85rem', textAlign: 'left', padding: '0 0.5rem', lineHeight: 1.8, listStyle: 'none', margin: '0 0 1.5rem' }}>
                            <li>✅ Full dashboard access</li>
                            <li>✅ AI menu import</li>
                            <li>✅ Order management</li>
                            <li>✅ Basic analytics</li>
                            <li>✅ Email notifications</li>
                        </ul>
                        <button
                            onClick={handleStartTrial}
                            disabled={subLoading || (subscription && subscription.trial_expired)}
                            style={{
                                width: '100%', padding: '12px', border: 'none', borderRadius: 10, cursor: 'pointer',
                                background: (subscription && subscription.trial_expired) ? '#555' : 'linear-gradient(135deg, #4ade80, #22c55e)',
                                color: (subscription && subscription.trial_expired) ? '#999' : '#000',
                                fontWeight: 700, fontSize: '1rem', marginTop: 'auto',
                                opacity: subLoading ? 0.6 : 1,
                                cursor: (subscription && subscription.trial_expired) ? 'not-allowed' : 'pointer'
                            }}
                        >
                            {(subscription && subscription.trial_expired) ? '❌ Trial Used' : subLoading ? '⏳ Starting...' : '🚀 Start Free Trial'}
                        </button>
                    </div>

                    {/* Standard */}
                    <div style={{
                        background: 'linear-gradient(145deg, #0f172a, #1e293b)', borderRadius: 16, padding: '2rem 1.5rem',
                        border: '2px solid #f59e0b', display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center',
                        position: 'relative', boxShadow: '0 0 30px rgba(245, 158, 11, 0.15)'
                    }}>
                        <div style={{
                            position: 'absolute', top: -12, background: '#f59e0b', color: '#000', padding: '3px 14px',
                            borderRadius: 20, fontSize: '0.7rem', fontWeight: 800, letterSpacing: 1
                        }}>MOST POPULAR</div>
                        <div style={{ fontSize: '2.5rem', marginBottom: 8 }}>💼</div>
                        <h3 style={{ color: '#fff', margin: '0.5rem 0', fontSize: '1.3rem' }}>Standard</h3>
                        <div style={{ fontSize: '2rem', fontWeight: 800, color: '#f59e0b', marginBottom: 4 }}>$230</div>
                        <div style={{ color: '#888', fontSize: '0.85rem', marginBottom: 16 }}>per month</div>
                        <ul style={{ color: '#ccc', fontSize: '0.85rem', textAlign: 'left', padding: '0 0.5rem', lineHeight: 1.8, listStyle: 'none', margin: '0 0 1.5rem' }}>
                            <li>✅ Everything in Free Trial</li>
                            <li>✅ Unlimited restaurants</li>
                            <li>✅ Priority support</li>
                            <li>✅ Weekly sales reports</li>
                            <li>✅ SMS notifications</li>
                        </ul>
                        <button
                            onClick={() => handleSubscribe('standard')} disabled={subLoading}
                            style={{
                                width: '100%', padding: '12px', border: 'none', borderRadius: 10, cursor: 'pointer',
                                background: 'linear-gradient(135deg, #f59e0b, #d97706)', color: '#000',
                                fontWeight: 700, fontSize: '1rem', marginTop: 'auto',
                                opacity: subLoading ? 0.6 : 1
                            }}
                        >
                            {subLoading ? '⏳ Processing...' : '💳 Subscribe — $230/mo'}
                        </button>
                    </div>

                    {/* Corporate */}
                    <div style={{
                        background: 'linear-gradient(145deg, #1a0a2e, #2d1b69)', borderRadius: 16, padding: '2rem 1.5rem',
                        border: '1px solid #7c3aed', display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center'
                    }}>
                        <div style={{ fontSize: '2.5rem', marginBottom: 8 }}>🏢</div>
                        <h3 style={{ color: '#fff', margin: '0.5rem 0', fontSize: '1.3rem' }}>Corporate</h3>
                        <div style={{ fontSize: '2rem', fontWeight: 800, color: '#a78bfa', marginBottom: 4 }}>$400</div>
                        <div style={{ color: '#888', fontSize: '0.85rem', marginBottom: 16 }}>per month</div>
                        <ul style={{ color: '#ccc', fontSize: '0.85rem', textAlign: 'left', padding: '0 0.5rem', lineHeight: 1.8, listStyle: 'none', margin: '0 0 1.5rem' }}>
                            <li>✅ Everything in Standard</li>
                            <li>✅ Daily sales reports</li>
                            <li>✅ Advanced charts & insights</li>
                            <li>✅ Multi-location support</li>
                            <li>✅ Dedicated account manager</li>
                            <li>✅ Custom branding</li>
                        </ul>
                        <button
                            onClick={() => handleSubscribe('corporate')} disabled={subLoading}
                            style={{
                                width: '100%', padding: '12px', border: 'none', borderRadius: 10, cursor: 'pointer',
                                background: 'linear-gradient(135deg, #8b5cf6, #7c3aed)', color: '#fff',
                                fontWeight: 700, fontSize: '1rem', marginTop: 'auto',
                                opacity: subLoading ? 0.6 : 1
                            }}
                        >
                            {subLoading ? '⏳ Processing...' : '💎 Subscribe — $400/mo'}
                        </button>
                    </div>
                </div>
                {subscription && (subscription.status === 'canceled' || subscription.status === 'expired') && !subscription.trial_expired && (
                    <p style={{ textAlign: 'center', color: '#ef4444', marginTop: '1rem', fontSize: '0.9rem' }}>
                        Your subscription has been canceled. Choose a plan to reactivate.
                    </p>
                )}
            </div>
        );
    }

    return (
        <div className="owner-portal">
            <div className="owner-header">
                <h2>🍽️ Owner Dashboard</h2>
                <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
                    {subscription && (
                        <span style={{
                            background: subscription.plan === 'corporate' ? '#7c3aed' : subscription.plan === 'standard' ? '#f59e0b' : '#4ade80',
                            color: subscription.plan === 'standard' ? '#000' : '#fff',
                            padding: '3px 10px', borderRadius: 12, fontSize: '0.72rem', fontWeight: 700, textTransform: 'uppercase',
                            display: 'flex', alignItems: 'center', gap: 6
                        }}>
                            {subscription.plan === 'free_trial' ? '🆓 Trial' : subscription.plan === 'corporate' ? '🏢 Corporate' : '💼 Standard'}
                            {subscription.days_remaining != null && subscription.plan === 'free_trial' && (
                                <span style={{ fontSize: '0.65rem', opacity: 0.9 }}>({subscription.days_remaining}d left)</span>
                            )}
                        </span>
                    )}
                    <span className="owner-email">{user.email}</span>
                    <button className="owner-back-btn" onClick={onBack}>Logout</button>
                </div>
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
                            <label>Restaurant Name *<input value={restName} onChange={(e) => setRestName(e.target.value)} required placeholder="e.g. Joe's Pizza" /></label>
                            <label>City *<input value={restCity} onChange={(e) => setRestCity(e.target.value)} required placeholder="e.g. Lancaster" /></label>
                            <label>Address<input value={restAddress} onChange={(e) => setRestAddress(e.target.value)} placeholder="123 Main St" /></label>
                            <label>Zipcode<input value={restZipcode} onChange={(e) => setRestZipcode(e.target.value)} placeholder="29720" /></label>
                            <label>Phone<input value={restPhone} onChange={(e) => setRestPhone(e.target.value)} placeholder="803-555-1234" /></label>
                            <label>Description<input value={restDesc} onChange={(e) => setRestDesc(e.target.value)} placeholder="Best pizza in town" /></label>
                            <label>Latitude<input value={restLat} onChange={(e) => setRestLat(e.target.value)} placeholder="34.72" /></label>
                            <label>Longitude<input value={restLng} onChange={(e) => setRestLng(e.target.value)} placeholder="-80.77" /></label>
                        </div>
                        <button type="submit" className="owner-primary-btn">Create Restaurant</button>
                    </form>
                )}

                {myRestaurants.length === 0 && !showCreate && (
                    <p className="owner-empty">No restaurants yet. Click "+ Add Restaurant" to get started.</p>
                )}

                {/* Restaurant list with tabs */}
                <div className="owner-restaurants-list">
                    {myRestaurants.map((r) => {
                        const tab = getTab(r.id);
                        const view = ordersView[r.id] || "active";
                        const rOrders = orders[r.id] || [];
                        const rArchived = archivedOrders[r.id] || { orders: [], total: 0, page: 1, total_pages: 0 };
                        const newOrderCount = rOrders.filter((o) => o.status === "confirmed").length;
                        return (
                            <div key={r.id} className="owner-restaurant-block">
                                {/* Restaurant header */}
                                <div className="owner-restaurant-item">
                                    <div className="owner-restaurant-info">
                                        <strong>{r.name}</strong>
                                        <span className="owner-restaurant-meta">{r.city} · #{r.slug}</span>
                                    </div>
                                    {newOrderCount > 0 && (
                                        <span className="owner-new-order-badge">{newOrderCount} new</span>
                                    )}
                                </div>

                                {/* Tab buttons */}
                                <div className="owner-tab-bar">
                                    <button className={`owner-tab-btn ${tab === "orders" ? "active" : ""}`} onClick={() => setTab(r.id, "orders")}>
                                        📋 Orders {newOrderCount > 0 && <span className="owner-tab-badge">{newOrderCount}</span>}
                                    </button>
                                    <button className={`owner-tab-btn ${tab === "sales" ? "active" : ""}`} onClick={() => setTab(r.id, "sales")}>
                                        📊 Sales
                                    </button>
                                    <button className={`owner-tab-btn ${tab === "menu" ? "active" : ""}`} onClick={() => setTab(r.id, "menu")}>
                                        🍽️ Menu
                                    </button>
                                    <button className={`owner-tab-btn ${tab === "extract" ? "active" : ""}`} onClick={() => { setTab(r.id, "extract"); setImportRestId(r.id); setExtractMode(null); setImportedMenu(null); setImportError(""); setSaveStatus(""); setSaveError(""); }}>
                                        🤖 Extract
                                    </button>
                                    <button className={`owner-tab-btn ${tab === "settings" ? "active" : ""}`} onClick={() => setTab(r.id, "settings")}>
                                        ⚙️ Settings
                                    </button>
                                </div>

                                {/* ORDERS TAB */}
                                {tab === "orders" && (
                                    <div className="owner-orders-panel">
                                        {/* Customer complaints (escalated feedback) */}
                                        {(complaints[r.id] || []).length > 0 && (
                                            <div className="owner-complaints-box">
                                                <div className="owner-complaints-title">⚠️ Customer complaints (need attention)</div>
                                                {(complaints[r.id] || []).slice(0, 10).map((c) => (
                                                    <div key={c.id} className="owner-complaint-item">
                                                        <div className="owner-complaint-meta">Order #{c.order_id} · {c.rating}★</div>
                                                        <div className="owner-complaint-issues">{Array.isArray(c.issues) ? c.issues.join(", ") : ""}</div>
                                                        {c.comment && <div className="owner-complaint-comment">{c.comment}</div>}
                                                    </div>
                                                ))}
                                            </div>
                                        )}
                                        {/* Active / Archived toggle */}
                                        <div className="owner-orders-toggle">
                                            <button
                                                className={`owner-orders-toggle-btn ${view === "active" ? "active" : ""}`}
                                                onClick={() => setOrdersView((p) => ({ ...p, [r.id]: "active" }))}
                                            >
                                                📋 Active {rOrders.length > 0 && <span className="owner-tab-badge">{rOrders.length}</span>}
                                            </button>
                                            <button
                                                className={`owner-orders-toggle-btn ${view === "archived" ? "active" : ""}`}
                                                onClick={() => {
                                                    setOrdersView((p) => ({ ...p, [r.id]: "archived" }));
                                                    if (!archivedOrders[r.id]) {
                                                        const filters = { search: orderSearch[r.id] || undefined, dateFrom: orderDateFrom[r.id] || undefined, dateTo: orderDateTo[r.id] || undefined };
                                                        loadArchivedOrders(r.id, 1, filters);
                                                    }
                                                }}
                                            >
                                                📁 Archived {rArchived.total > 0 && <span className="owner-tab-badge-muted">{rArchived.total}</span>}
                                            </button>
                                        </div>

                                        {/* Search & Date Filters */}
                                        <div className="owner-orders-filters">
                                            <div className="owner-search-row">
                                                <span className="owner-search-icon">🔍</span>
                                                <input
                                                    className="owner-search-input"
                                                    type="text"
                                                    placeholder="Search by order #, email, or item name..."
                                                    value={orderSearch[r.id] || ""}
                                                    onChange={(e) => handleOrderSearch(r.id, e.target.value)}
                                                />
                                            </div>
                                            <div className="owner-date-row">
                                                <label className="owner-date-field">
                                                    <span>From</span>
                                                    <input
                                                        type="date"
                                                        value={orderDateFrom[r.id] || ""}
                                                        onChange={(e) => handleDateFilter(r.id, "from", e.target.value)}
                                                    />
                                                </label>
                                                <label className="owner-date-field">
                                                    <span>To</span>
                                                    <input
                                                        type="date"
                                                        value={orderDateTo[r.id] || ""}
                                                        onChange={(e) => handleDateFilter(r.id, "to", e.target.value)}
                                                    />
                                                </label>
                                                {(orderSearch[r.id] || orderDateFrom[r.id] || orderDateTo[r.id]) && (
                                                    <button className="owner-clear-filters" onClick={() => clearOrderFilters(r.id)}>
                                                        ✕ Clear
                                                    </button>
                                                )}
                                            </div>
                                        </div>

                                        {/* ACTIVE ORDERS VIEW */}
                                        {view === "active" && (
                                            <>
                                                {ordersLoading[r.id] && rOrders.length === 0 && (
                                                    <p className="owner-loading-text">Loading orders...</p>
                                                )}
                                                {!ordersLoading[r.id] && rOrders.length === 0 && (
                                                    <p className="owner-empty">No active orders. Completed orders are in the Archived tab.</p>
                                                )}
                                                {rOrders.map((order) => (
                                                    <div key={order.id} className={`owner-order-card ${order.status === "confirmed" ? "owner-order-new" : ""}`}>
                                                        <div className="owner-order-header">
                                                            <span className="owner-order-id">Order #{order.id}</span>
                                                            <StatusBadge status={order.status} />
                                                        </div>
                                                        <div className="owner-order-meta">
                                                            <span>👤 {order.customer_email || "Guest"}</span>
                                                            <span>🕐 {new Date(order.created_at).toLocaleString()}</span>
                                                        </div>
                                                        <div className="owner-order-items">
                                                            {order.items.map((item, idx) => (
                                                                <div key={idx} className="owner-order-item-row">
                                                                    <span>{item.name} × {item.quantity}</span>
                                                                    <span>${(item.price_cents / 100).toFixed(2)}</span>
                                                                </div>
                                                            ))}
                                                        </div>
                                                        <div className="owner-order-total">
                                                            Total: <strong>${(order.total_cents / 100).toFixed(2)}</strong>
                                                        </div>
                                                        {order.status === "confirmed" && (
                                                            <div className="owner-order-actions">
                                                                <button className="owner-accept-btn" onClick={() => handleStatusChange(r.id, order.id, "accepted")}>✅ Accept</button>
                                                                <button className="owner-reject-btn" onClick={() => handleStatusChange(r.id, order.id, "rejected")}>❌ Reject</button>
                                                            </div>
                                                        )}
                                                        {order.status === "accepted" && (
                                                            <div className="owner-order-actions">
                                                                <button className="owner-preparing-btn" onClick={() => handleStatusChange(r.id, order.id, "preparing")}>🍳 Start Preparing</button>
                                                            </div>
                                                        )}
                                                        {order.status === "preparing" && (
                                                            <div className="owner-order-actions">
                                                                <button className="owner-ready-btn" onClick={() => handleStatusChange(r.id, order.id, "ready")}>📦 Mark Ready</button>
                                                            </div>
                                                        )}
                                                        {order.status === "ready" && (
                                                            <div className="owner-order-actions">
                                                                <button className="owner-complete-btn" onClick={() => handleStatusChange(r.id, order.id, "completed")}>✓ Complete</button>
                                                            </div>
                                                        )}
                                                    </div>
                                                ))}
                                            </>
                                        )}

                                        {/* ARCHIVED ORDERS VIEW */}
                                        {view === "archived" && (
                                            <>
                                                {archivedLoading[r.id] && (
                                                    <p className="owner-loading-text">Loading archived orders...</p>
                                                )}
                                                {!archivedLoading[r.id] && rArchived.orders.length === 0 && (
                                                    <p className="owner-empty">No archived orders yet.</p>
                                                )}
                                                {rArchived.orders.map((order) => (
                                                    <div key={order.id} className="owner-order-card owner-order-archived">
                                                        <div className="owner-order-header">
                                                            <span className="owner-order-id">Order #{order.id}</span>
                                                            <StatusBadge status={order.status} />
                                                        </div>
                                                        <div className="owner-order-meta">
                                                            <span>👤 {order.customer_email || "Guest"}</span>
                                                            <span>🕐 {new Date(order.created_at).toLocaleString()}</span>
                                                        </div>
                                                        <div className="owner-order-items">
                                                            {order.items.map((item, idx) => (
                                                                <div key={idx} className="owner-order-item-row">
                                                                    <span>{item.name} × {item.quantity}</span>
                                                                    <span>${(item.price_cents / 100).toFixed(2)}</span>
                                                                </div>
                                                            ))}
                                                        </div>
                                                        <div className="owner-order-total">
                                                            Total: <strong>${(order.total_cents / 100).toFixed(2)}</strong>
                                                        </div>
                                                    </div>
                                                ))}
                                                {/* Pagination */}
                                                {rArchived.total_pages > 1 && (
                                                    <div className="owner-archived-pagination">
                                                        <button
                                                            disabled={rArchived.page <= 1}
                                                            onClick={() => {
                                                                const filters = { search: orderSearch[r.id] || undefined, dateFrom: orderDateFrom[r.id] || undefined, dateTo: orderDateTo[r.id] || undefined };
                                                                loadArchivedOrders(r.id, rArchived.page - 1, filters);
                                                            }}
                                                        >← Prev</button>
                                                        <span>Page {rArchived.page} of {rArchived.total_pages}</span>
                                                        <button
                                                            disabled={rArchived.page >= rArchived.total_pages}
                                                            onClick={() => {
                                                                const filters = { search: orderSearch[r.id] || undefined, dateFrom: orderDateFrom[r.id] || undefined, dateTo: orderDateTo[r.id] || undefined };
                                                                loadArchivedOrders(r.id, rArchived.page + 1, filters);
                                                            }}
                                                        >Next →</button>
                                                    </div>
                                                )}
                                            </>
                                        )}
                                    </div>
                                )}

                                {/* MENU TAB */}
                                {tab === "menu" && (
                                    <div className="owner-menu-panel">
                                        <p className="owner-empty">Switch to the <strong>🤖 Extract</strong> tab to import menu from website or image.</p>
                                    </div>
                                )}

                                {/* EXTRACT TAB */}
                                {tab === "extract" && (
                                    <div className="owner-extract-panel">
                                        {!extractMode && !importedMenu && (
                                            <>
                                                <div className="extract-header">
                                                    <h4>📋 Extract Menu</h4>
                                                    <p className="extract-header-desc">Choose a source to automatically extract your restaurant menu</p>
                                                </div>
                                                <div className="extract-mode-cards">
                                                    <button className="extract-mode-card" onClick={() => { setExtractMode("url"); setImportedMenu(null); setImportError(""); }}>
                                                        <div className="extract-mode-icon">🌐</div>
                                                        <div className="extract-mode-title">Website</div>
                                                        <div className="extract-mode-desc">Auto-scrape from URL</div>
                                                        <div className="extract-mode-arrow">→</div>
                                                    </button>
                                                    <button className="extract-mode-card" onClick={() => { setExtractMode("image"); setImportedMenu(null); setImportError(""); }}>
                                                        <div className="extract-mode-icon">📸</div>
                                                        <div className="extract-mode-title">Photo</div>
                                                        <div className="extract-mode-desc">Upload menu image</div>
                                                        <div className="extract-mode-arrow">→</div>
                                                    </button>
                                                    <button className="extract-mode-card" onClick={() => { setExtractMode("document"); setImportedMenu(null); setImportError(""); }}>
                                                        <div className="extract-mode-icon">📄</div>
                                                        <div className="extract-mode-title">Document</div>
                                                        <div className="extract-mode-desc">PDF, Word, or Excel</div>
                                                        <div className="extract-mode-arrow">→</div>
                                                    </button>
                                                </div>
                                            </>
                                        )}

                                        {/* URL Mode */}
                                        {extractMode === "url" && !importedMenu && (
                                            <div className="extract-form">
                                                <div className="extract-form-header">
                                                    <button className="extract-back-btn" onClick={() => setExtractMode(null)}>← Back</button>
                                                    <span className="extract-form-step">Step 1 of 2</span>
                                                </div>
                                                <h4>🌐 Enter Restaurant Website</h4>
                                                <p className="extract-form-hint">Paste the menu page URL — our AI will scan the entire site and extract all items with prices.</p>
                                                <input
                                                    type="url"
                                                    placeholder="https://restaurant-website.com/menu"
                                                    value={importUrl}
                                                    onChange={(e) => setImportUrl(e.target.value)}
                                                    className="extract-url-input"
                                                />
                                                <button
                                                    className="extract-action-btn"
                                                    onClick={handleImportMenu}
                                                    disabled={importLoading || !importUrl.trim()}
                                                >
                                                    {importLoading ? "⏳ Scanning website..." : "🔍 Extract Menu from URL"}
                                                </button>
                                                {importLoading && (
                                                    <div className="extract-loading extract-loading-url">
                                                        <div className="extract-spinner"></div>
                                                        <div className="owner-progress-bar">
                                                            <div className="owner-progress-fill"></div>
                                                        </div>
                                                        <p className="extract-progress-hint">Scanning pages & extracting menu… This may take 1–3 minutes (or up to 5 for large sites). Please don’t close the page.</p>
                                                    </div>
                                                )}
                                            </div>
                                        )}

                                        {/* Image Mode */}
                                        {extractMode === "image" && !importedMenu && (
                                            <div className="extract-form">
                                                <div className="extract-form-header">
                                                    <button className="extract-back-btn" onClick={() => setExtractMode(null)}>← Back</button>
                                                    <span className="extract-form-step">Step 1 of 2</span>
                                                </div>
                                                <h4>📸 Upload Menu Photo</h4>
                                                <p className="extract-form-hint">Take a clear photo of the printed menu or capture a screenshot. Our AI will extract every item with prices.</p>
                                                <div
                                                    className={`extract-dropzone ${dragActive ? "active" : ""}`}
                                                    onDragOver={(e) => { e.preventDefault(); setDragActive(true); }}
                                                    onDragLeave={() => setDragActive(false)}
                                                    onDrop={(e) => {
                                                        e.preventDefault();
                                                        setDragActive(false);
                                                        if (e.dataTransfer.files[0]) handleExtractFromFile(e.dataTransfer.files[0], r.id);
                                                    }}
                                                    onClick={() => document.getElementById(`file-input-${r.id}`).click()}
                                                >
                                                    <input
                                                        id={`file-input-${r.id}`}
                                                        type="file"
                                                        accept=".jpg,.jpeg,.png,.webp"
                                                        style={{ display: 'none' }}
                                                        onChange={(e) => { if (e.target.files[0]) handleExtractFromFile(e.target.files[0], r.id); }}
                                                    />
                                                    {importLoading ? (
                                                        <div className="extract-loading">
                                                            <div className="extract-spinner"></div>
                                                            <p>🧠 AI is analyzing your menu...</p>
                                                            <p className="extract-loading-sub">This may take 15-30 seconds</p>
                                                        </div>
                                                    ) : (
                                                        <>
                                                            <div className="extract-dropzone-icon">📷</div>
                                                            <p className="extract-dropzone-text">Drag & drop a menu photo here</p>
                                                            <p className="extract-dropzone-sub">or tap to browse · JPG, PNG, WebP · Max 10MB</p>
                                                        </>
                                                    )}
                                                </div>
                                            </div>
                                        )}

                                        {/* Document Mode */}
                                        {extractMode === "document" && !importedMenu && (
                                            <div className="extract-form">
                                                <div className="extract-form-header">
                                                    <button className="extract-back-btn" onClick={() => setExtractMode(null)}>← Back</button>
                                                    <span className="extract-form-step">Step 1 of 2</span>
                                                </div>
                                                <h4>📄 Upload Menu Document</h4>
                                                <p className="extract-form-hint">Upload a PDF, Word, or Excel file containing your menu. Our AI will extract all items and prices automatically.</p>
                                                <div
                                                    className={`extract-dropzone ${dragActive ? "active" : ""}`}
                                                    onDragOver={(e) => { e.preventDefault(); setDragActive(true); }}
                                                    onDragLeave={() => setDragActive(false)}
                                                    onDrop={(e) => {
                                                        e.preventDefault();
                                                        setDragActive(false);
                                                        if (e.dataTransfer.files[0]) handleExtractFromFile(e.dataTransfer.files[0], r.id);
                                                    }}
                                                    onClick={() => document.getElementById(`doc-input-${r.id}`).click()}
                                                >
                                                    <input
                                                        id={`doc-input-${r.id}`}
                                                        type="file"
                                                        accept=".pdf,.docx,.doc,.xlsx,.xls"
                                                        style={{ display: 'none' }}
                                                        onChange={(e) => { if (e.target.files[0]) handleExtractFromFile(e.target.files[0], r.id); }}
                                                    />
                                                    {importLoading ? (
                                                        <div className="extract-loading">
                                                            <div className="extract-spinner"></div>
                                                            <p>🧠 AI is analyzing your document...</p>
                                                            <p className="extract-loading-sub">Extracting text & parsing menu — 15-30 seconds</p>
                                                        </div>
                                                    ) : (
                                                        <>
                                                            <div className="extract-dropzone-icon">📁</div>
                                                            <p className="extract-dropzone-text">Drag & drop a menu file here</p>
                                                            <p className="extract-dropzone-sub">or tap to browse · PDF, DOCX, XLSX · Max 20MB</p>
                                                        </>
                                                    )}
                                                </div>
                                            </div>
                                        )}

                                        {/* Error */}
                                        {importError && (
                                            <div className="extract-error">
                                                ❌ {importError}
                                                <button onClick={() => setImportError("")}>✕</button>
                                            </div>
                                        )}

                                        {/* Preview & Edit */}
                                        {importedMenu && importedMenu.categories && (
                                            <div className="extract-preview">
                                                <div className="extract-preview-header">
                                                    <h4>✅ Extracted Menu — Review & Edit</h4>
                                                    <div style={{ display: 'flex', gap: 8 }}>
                                                        <button className="extract-back-btn" onClick={() => { setImportedMenu(null); setExtractMode(null); setSaveStatus(""); setSaveError(""); }}>← New Extract</button>
                                                    </div>
                                                </div>
                                                {importedMenu.restaurant_name && (
                                                    <p className="extract-restaurant-name">📍 {importedMenu.restaurant_name}</p>
                                                )}
                                                <p className="extract-item-count">
                                                    {importedMenu.categories.reduce((s, c) => s + (c.items?.length || 0), 0)} items in {importedMenu.categories.length} categories
                                                </p>

                                                {importedMenu.categories.map((cat, ci) => (
                                                    <div key={ci} className="extract-category">
                                                        <input
                                                            className="extract-cat-name"
                                                            value={cat.name}
                                                            onChange={(e) => updateCategoryName(ci, e.target.value)}
                                                        />
                                                        {cat.items.map((item, ii) => (
                                                            <div key={ii} className="extract-item-row">
                                                                <input
                                                                    className="extract-item-name"
                                                                    value={item.name}
                                                                    onChange={(e) => updateItem(ci, ii, "name", e.target.value)}
                                                                    placeholder="Item name"
                                                                />
                                                                <input
                                                                    className="extract-item-price"
                                                                    type="number"
                                                                    step="0.01"
                                                                    value={item.price || 0}
                                                                    onChange={(e) => updateItem(ci, ii, "price", e.target.value)}
                                                                />
                                                                <button className="extract-item-del" onClick={() => deleteItem(ci, ii)}>✕</button>
                                                            </div>
                                                        ))}
                                                        <button className="extract-add-item" onClick={() => addItem(ci)}>+ Add Item</button>
                                                    </div>
                                                ))}
                                                <button className="extract-add-cat" onClick={addCategory}>+ Add Category</button>

                                                <button
                                                    className="owner-primary-btn extract-save-btn"
                                                    onClick={handleSaveMenu}
                                                    disabled={saveStatus === "saving"}
                                                >
                                                    {saveStatus === "saving" ? "⏳ Saving..." : saveStatus === "saved" ? "✅ Saved!" : "💾 Save to Menu"}
                                                </button>
                                                {saveStatus === "error" && <p className="extract-error" title={saveError}>{saveError || "Failed to save. Try again."}</p>}
                                            </div>
                                        )}
                                    </div>
                                )}

                                {/* SALES TAB */}
                                {tab === "sales" && (
                                    <div className="owner-sales-panel">
                                        <SalesAnalytics token={token} restaurantId={r.id} restaurantName={r.name} />
                                    </div>
                                )}

                                {/* SETTINGS TAB */}
                                {tab === "settings" && (
                                    <div className="owner-settings-panel">
                                        <h4>📧 Notification Settings</h4>
                                        <p className="owner-settings-desc">Get notified when new orders come in. Leave blank to use your login email.</p>
                                        <div className="owner-settings-form">
                                            <label>
                                                Notification Email
                                                <input
                                                    type="email"
                                                    value={notifEmail[r.id] || ""}
                                                    onChange={(e) => setNotifEmail((p) => ({ ...p, [r.id]: e.target.value }))}
                                                    placeholder={user.email}
                                                />
                                            </label>
                                            <label>
                                                Phone (for SMS/WhatsApp)
                                                <input
                                                    type="tel"
                                                    value={notifPhone[r.id] || ""}
                                                    onChange={(e) => setNotifPhone((p) => ({ ...p, [r.id]: e.target.value }))}
                                                    placeholder="+1 803-555-1234"
                                                />
                                            </label>
                                            <button
                                                className="owner-primary-btn"
                                                onClick={() => handleSaveNotifications(r.id)}
                                                disabled={notifSaving[r.id]}
                                            >
                                                {notifSaving[r.id] ? "Saving..." : "💾 Save Notification Settings"}
                                            </button>
                                        </div>
                                        <hr style={{ border: 'none', borderTop: '1px solid #333', margin: '1.5rem 0' }} />
                                        <h4>💳 Subscription & Billing</h4>
                                        <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap', marginTop: '0.75rem' }}>
                                            {subscription && subscription.plan === 'free_trial' && (
                                                <button
                                                    className="owner-primary-btn"
                                                    style={{ background: 'linear-gradient(135deg, #f59e0b, #d97706)', border: 'none', color: '#000' }}
                                                    onClick={() => { setSubscription(null); }}
                                                >
                                                    ⬆️ Upgrade Plan
                                                </button>
                                            )}
                                            {subscription && subscription.plan !== 'free_trial' && (
                                                <button
                                                    className="owner-primary-btn"
                                                    style={{ background: '#333', border: '1px solid #555' }}
                                                    onClick={handleManageBilling}
                                                >
                                                    🔧 Manage Billing
                                                </button>
                                            )}
                                            <div style={{ color: '#888', fontSize: '0.8rem', display: 'flex', alignItems: 'center' }}>
                                                Current plan: <strong style={{ color: '#fff', marginLeft: 4 }}>
                                                    {subscription?.plan === 'free_trial' ? 'Free Trial' : subscription?.plan === 'standard' ? 'Standard ($230/mo)' : 'Corporate ($400/mo)'}
                                                </strong>
                                                {subscription?.days_remaining != null && subscription?.plan === 'free_trial' && (
                                                    <span style={{ marginLeft: 8, color: subscription.days_remaining <= 5 ? '#ef4444' : '#4ade80' }}>
                                                        • {subscription.days_remaining} days remaining
                                                    </span>
                                                )}
                                            </div>
                                        </div>
                                    </div>
                                )}
                            </div>
                        );
                    })}
                </div>
            </div>

            {/* AI Menu Import Modal Overlay — only show when NOT on Extract tab */}
            {importRestId && !Object.values(activeTab).includes("extract") && (
                <div className="owner-modal-overlay" onClick={(e) => { if (e.target === e.currentTarget) setImportRestId(null); }}>
                    <div className="owner-modal">
                        {/* Scrollable body */}
                        <div className="owner-modal-body">
                            <div className="owner-modal-header">
                                <h3>
                                    🤖 AI Menu Import
                                    <span className="owner-import-for">
                                        for {myRestaurants.find((r) => r.id === importRestId)?.name}
                                    </span>
                                </h3>
                                <button className="owner-modal-close" onClick={() => setImportRestId(null)}>✕</button>
                            </div>
                            <p className="owner-modal-desc">Paste the restaurant's website/menu URL and our AI will extract the full menu automatically.</p>

                            <div className="owner-import-row">
                                <input
                                    className="owner-import-input"
                                    value={importUrl}
                                    onChange={(e) => setImportUrl(e.target.value)}
                                    placeholder="https://restaurant-website.com/menu"
                                    autoFocus
                                />
                                <button
                                    className="owner-extract-btn"
                                    onClick={handleImportMenu}
                                    disabled={importLoading}
                                >
                                    {importLoading ? "⏳ Extracting..." : "🔮 Extract Menu"}
                                </button>
                            </div>

                            {importLoading && (
                                <div className="owner-import-loading">
                                    <div className="extract-spinner"></div>
                                    <div className="owner-progress-bar">
                                        <div className="owner-progress-fill"></div>
                                    </div>
                                    <p>Crawling menu pages with JS rendering… This may take 1–3 minutes (or up to 5 for large sites). Please don’t close the page.</p>
                                </div>
                            )}

                            {importError && <p className="owner-error">{importError}</p>}

                            {importedMenu && (
                                <div className="owner-extracted">
                                    <div className="owner-extracted-header">
                                        <h4>✅ Extracted: {importedMenu.restaurant_name || "Menu"}</h4>
                                        <span className="owner-extracted-stats">
                                            {importedMenu.pages_scraped > 1 && `${importedMenu.pages_scraped} pages · `}
                                            {importedMenu.categories?.length || 0} categories · {importedMenu.categories?.reduce((s, c) => s + (c.items?.length || 0), 0) || 0} items
                                        </span>
                                    </div>

                                    <div className="owner-edit-hint">✏️ Edit names, descriptions, and prices below. Use "+ Add Item" to add items manually.</div>

                                    <div className="owner-menu-preview">
                                        {importedMenu.categories?.map((cat, ci) => (
                                            <div key={ci} className="owner-menu-category">
                                                <div className="owner-cat-header">
                                                    <input
                                                        className="owner-cat-name-input"
                                                        value={cat.name}
                                                        onChange={(e) => updateCategoryName(ci, e.target.value)}
                                                    />
                                                    <span className="owner-item-count">{cat.items?.length || 0}</span>
                                                </div>
                                                {cat.items?.map((item, ii) => (
                                                    <div key={ii} className="owner-menu-item-row">
                                                        <div className="owner-item-fields">
                                                            <input className="owner-item-name" value={item.name} onChange={(e) => updateItem(ci, ii, "name", e.target.value)} placeholder="Item name" />
                                                            <input className="owner-item-desc" value={item.description || ""} onChange={(e) => updateItem(ci, ii, "description", e.target.value)} placeholder="Description" />
                                                        </div>
                                                        <div className="owner-item-price-group">
                                                            <span className="owner-dollar">$</span>
                                                            <input className="owner-item-price" type="number" step="0.01" value={item.price || 0} onChange={(e) => updateItem(ci, ii, "price", e.target.value)} />
                                                            <button className="owner-item-delete" onClick={() => deleteItem(ci, ii)}>✕</button>
                                                        </div>
                                                    </div>
                                                ))}
                                                <button className="owner-add-item-btn" onClick={() => addItem(ci)}>+ Add Item</button>
                                            </div>
                                        ))}
                                        <button className="owner-add-cat-btn" onClick={addCategory}>+ Add Category</button>
                                    </div>
                                </div>
                            )}
                        </div>

                        {/* Sticky footer with save button — always visible */}
                        {importedMenu && (
                            <div className="owner-modal-footer">
                                <button className="owner-save-btn" onClick={handleSaveMenu} disabled={saveStatus === "saving"}>
                                    {saveStatus === "saving" ? "⏳ Saving..." : saveStatus === "saved" ? "✅ Saved Successfully!" : "💾 Save Menu to Restaurant"}
                                </button>
                                {saveStatus === "error" && <span style={{ color: "#fca5a5", fontSize: "0.85rem" }} title={saveError}>{saveError || "Failed to save. Try again."}</span>}
                            </div>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
}
