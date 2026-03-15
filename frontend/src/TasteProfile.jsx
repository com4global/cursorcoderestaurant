/**
 * AI Flavor Profile & Personalized Recommendations
 * Separate tab: taste preferences onboarding and "Based on your taste, try..." suggestions.
 */
import { useEffect, useState } from "react";
import { getTasteProfile, updateTasteProfile, getTasteRecommendations } from "./api.js";

const SPICE_OPTIONS = [
  { value: "mild", label: "Mild", emoji: "🥛" },
  { value: "medium", label: "Medium", emoji: "🌶️" },
  { value: "spicy", label: "Spicy", emoji: "🔥" },
];

const DIET_OPTIONS = [
  { value: "any", label: "No preference", emoji: "🍽️" },
  { value: "vegetarian", label: "Vegetarian", emoji: "🥬" },
  { value: "vegan", label: "Vegan", emoji: "🌱" },
  { value: "halal", label: "Halal", emoji: "☪️" },
];

const CUISINE_LIKES = [
  "Indian", "Italian", "Thai", "Chinese", "Mexican", "American",
  "Mediterranean", "Japanese", "Korean", "Middle Eastern",
];

export default function TasteProfile({ token, onNavigateToRestaurant }) {
  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  // Form state (explicit preferences)
  const [spiceLevel, setSpiceLevel] = useState("medium");
  const [diet, setDiet] = useState("any");
  const [likedCuisines, setLikedCuisines] = useState([]);
  const [dislikedTags, setDislikedTags] = useState("");
  const [recommendations, setRecommendations] = useState([]);

  useEffect(() => {
    if (!token) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    getTasteProfile(token)
      .then((data) => {
        if (!cancelled) {
          setProfile(data);
          if (data.spice_level) setSpiceLevel(data.spice_level);
          if (data.diet) setDiet(data.diet);
          if (data.liked_cuisines?.length) setLikedCuisines(data.liked_cuisines);
          if (data.disliked_tags) setDislikedTags(data.disliked_tags);
        }
      })
      .catch((err) => {
        if (!cancelled) setError(err.message || "Failed to load profile");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [token]);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    getTasteRecommendations(token, 10)
      .then((list) => { if (!cancelled) setRecommendations(list || []); })
      .catch(() => { if (!cancelled) setRecommendations([]); });
    return () => { cancelled = true; };
  }, [token, profile?.updated_at]);

  const toggleCuisine = (cuisine) => {
    setLikedCuisines((prev) =>
      prev.includes(cuisine) ? prev.filter((c) => c !== cuisine) : [...prev, cuisine]
    );
  };

  const handleSave = async () => {
    if (!token) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await updateTasteProfile(token, {
        spice_level: spiceLevel,
        diet,
        liked_cuisines: likedCuisines,
        disliked_tags: dislikedTags.trim() || null,
      });
      setProfile(updated);
    } catch (err) {
      setError(err.message || "Failed to save");
    } finally {
      setSaving(false);
    }
  };

  if (!token) {
    return (
      <div className="taste-page">
        <div className="taste-header">
          <span className="taste-header-emoji">🧠</span>
          <h1 className="taste-title">AI Flavor Profile</h1>
          <p className="taste-subtitle">Personalized recommendations based on your taste</p>
        </div>
        <div className="taste-empty">
          <div className="taste-empty-emoji">🔐</div>
          <p className="taste-empty-text">Sign in to set your preferences and get recommendations</p>
          <p className="taste-empty-hint">Go to the Profile tab to log in</p>
        </div>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="taste-page">
        <div className="taste-header">
          <span className="taste-header-emoji">🧠</span>
          <h1 className="taste-title">AI Flavor Profile</h1>
        </div>
        <div className="taste-loading">Loading your taste profile…</div>
      </div>
    );
  }

  return (
    <div className="taste-page">
      <div className="taste-header">
        <span className="taste-header-emoji">🧠</span>
        <h1 className="taste-title">AI Flavor Profile</h1>
        <p className="taste-subtitle">We use this to suggest dishes you’ll love</p>
      </div>

      {error && (
        <div className="taste-error" role="alert">
          {error}
        </div>
      )}

      <section className="taste-section">
        <h2 className="taste-section-title">Spice level</h2>
        <div className="taste-options">
          {SPICE_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              type="button"
              className={`taste-option-btn ${spiceLevel === opt.value ? "active" : ""}`}
              onClick={() => setSpiceLevel(opt.value)}
            >
              <span className="taste-option-emoji">{opt.emoji}</span>
              <span>{opt.label}</span>
            </button>
          ))}
        </div>
      </section>

      <section className="taste-section">
        <h2 className="taste-section-title">Diet</h2>
        <div className="taste-options">
          {DIET_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              type="button"
              className={`taste-option-btn ${diet === opt.value ? "active" : ""}`}
              onClick={() => setDiet(opt.value)}
            >
              <span className="taste-option-emoji">{opt.emoji}</span>
              <span>{opt.label}</span>
            </button>
          ))}
        </div>
      </section>

      <section className="taste-section">
        <h2 className="taste-section-title">Cuisines I like</h2>
        <p className="taste-section-hint">Tap to toggle</p>
        <div className="taste-chips">
          {CUISINE_LIKES.map((c) => (
            <button
              key={c}
              type="button"
              className={`taste-chip ${likedCuisines.includes(c) ? "active" : ""}`}
              onClick={() => toggleCuisine(c)}
            >
              {c}
            </button>
          ))}
        </div>
      </section>

      <section className="taste-section">
        <h2 className="taste-section-title">Avoid (optional)</h2>
        <input
          type="text"
          className="taste-input"
          placeholder="e.g. nuts, dairy, gluten"
          value={dislikedTags}
          onChange={(e) => setDislikedTags(e.target.value)}
        />
      </section>

      <div className="taste-actions">
        <button
          type="button"
          className="taste-save-btn"
          onClick={handleSave}
          disabled={saving}
        >
          {saving ? "Saving…" : "Save preferences"}
        </button>
      </div>

      {profile?.updated_at && (
        <p className="taste-updated">Last updated {new Date(profile.updated_at).toLocaleDateString()}</p>
      )}

      <section className="taste-section taste-recommendations-section">
        <h2 className="taste-section-title">Personalized picks</h2>
        {recommendations.length === 0 ? (
          <p className="taste-placeholder-text">Recommendations will appear here once we learn from your orders and preferences.</p>
        ) : (
          <ul className="taste-recommendations-list">
            {recommendations.map((rec) => (
              <li key={`${rec.restaurant_id}-${rec.menu_item_id}`} className="taste-rec-item">
                <div className="taste-rec-name">{rec.name}</div>
                <div className="taste-rec-meta">🍽️ {rec.restaurant_name} · ${(rec.price_cents / 100).toFixed(2)}</div>
                <div className="taste-rec-reason">{rec.reason}</div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
