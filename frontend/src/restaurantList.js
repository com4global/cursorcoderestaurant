function normalizePart(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function buildRestaurantDedupKey(restaurant) {
  const name = normalizePart(restaurant?.name);
  const city = normalizePart(restaurant?.city);
  const address = normalizePart(restaurant?.address);
  const zipcode = normalizePart(restaurant?.zipcode);
  const location = city || address || zipcode;
  return [name, location].join("|");
}

function scoreRestaurantRecord(restaurant) {
  let score = 0;
  if (restaurant?.distance_miles != null) score += 4;
  if (restaurant?.rating != null) score += 2;
  if (restaurant?.address) score += 2;
  if (restaurant?.city) score += 1;
  if (restaurant?.zipcode) score += 1;
  return score;
}

export function dedupeRestaurants(restaurants = []) {
  const deduped = new Map();

  for (const restaurant of restaurants) {
    const key = buildRestaurantDedupKey(restaurant);
    if (!key || key === "|") continue;

    const existing = deduped.get(key);
    if (!existing) {
      deduped.set(key, restaurant);
      continue;
    }

    const currentScore = scoreRestaurantRecord(restaurant);
    const existingScore = scoreRestaurantRecord(existing);

    if (currentScore > existingScore) {
      deduped.set(key, restaurant);
      continue;
    }

    if (currentScore === existingScore) {
      const currentDistance = restaurant?.distance_miles ?? Number.POSITIVE_INFINITY;
      const existingDistance = existing?.distance_miles ?? Number.POSITIVE_INFINITY;
      if (currentDistance < existingDistance) {
        deduped.set(key, restaurant);
      }
    }
  }

  return Array.from(deduped.values());
}