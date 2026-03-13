"""
Comprehensive test suite for the intent extraction engine.
Tests 120+ query variations covering all user scenarios.
"""
import pytest
import sys
import os

# Add the backend directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.intent_extractor import extract_intent_local, FoodIntent


# ─── Helper ─────────────────────────────────────────────────────────────────

def intent(text: str) -> FoodIntent:
    """Shorthand for extract_intent_local."""
    return extract_intent_local(text)


# ═══════════════════════════════════════════════════════════════════════════
# 🍔 BASIC FOOD REQUESTS (10 tests)
# ═══════════════════════════════════════════════════════════════════════════

class TestBasicFoodRequests:
    def test_pizza(self):
        r = intent("I want pizza")
        assert r.dish_name == "pizza"

    def test_burgers(self):
        r = intent("Show me burgers near me")
        assert r.dish_name == "burgers"

    def test_chicken_biryani(self):
        r = intent("I want chicken biryani")
        assert r.dish_name and "biryani" in r.dish_name
        assert r.protein_type == "chicken"

    def test_ramen(self):
        r = intent("Order ramen")
        assert r.dish_name == "ramen"

    def test_tacos(self):
        r = intent("Find tacos nearby")
        assert r.dish_name == "tacos"

    def test_pasta(self):
        r = intent("I feel like eating pasta")
        assert r.dish_name == "pasta"

    def test_sushi(self):
        r = intent("Show me sushi restaurants")
        assert r.dish_name and "sushi" in r.dish_name

    def test_fried_rice(self):
        r = intent("I want fried rice")
        assert r.dish_name and "fried rice" in r.dish_name

    def test_shawarma(self):
        r = intent("Get me shawarma")
        assert r.dish_name == "shawarma"

    def test_sandwich(self):
        r = intent("Find a good sandwich")
        assert r.dish_name == "sandwich"


# ═══════════════════════════════════════════════════════════════════════════
# 🌶 CUISINE SPECIFIC (10 tests)
# ═══════════════════════════════════════════════════════════════════════════

class TestCuisineSpecific:
    def test_indian(self):
        r = intent("Show Indian food near me")
        assert r.cuisine == "Indian"

    def test_chinese(self):
        r = intent("I want Chinese food")
        assert r.cuisine == "Chinese"

    def test_italian(self):
        r = intent("Find Italian restaurants")
        assert r.cuisine == "Italian"

    def test_thai(self):
        r = intent("I feel like eating Thai food")
        assert r.cuisine == "Thai"

    def test_mexican(self):
        r = intent("Show Mexican food nearby")
        assert r.cuisine == "Mexican"

    def test_japanese(self):
        r = intent("Japanese food open now")
        assert r.cuisine == "Japanese"

    def test_korean(self):
        r = intent("Korean BBQ near me")
        assert r.cuisine == "Korean"

    def test_mediterranean(self):
        r = intent("Mediterranean food nearby")
        assert r.cuisine == "Mediterranean"

    def test_vietnamese(self):
        r = intent("Find Vietnamese pho")
        assert r.cuisine == "Vietnamese"
        assert r.dish_name == "pho"

    def test_turkish(self):
        r = intent("Show Turkish food")
        assert r.cuisine == "Turkish"


# ═══════════════════════════════════════════════════════════════════════════
# 🍗 PROTEIN SPECIFIC (10 tests)
# ═══════════════════════════════════════════════════════════════════════════

class TestProteinSpecific:
    def test_chicken(self):
        r = intent("I want chicken dishes")
        assert r.protein_type == "chicken"

    def test_beef(self):
        r = intent("Show me beef burgers")
        assert r.protein_type == "beef"
        assert r.dish_name and "burgers" in r.dish_name

    def test_seafood(self):
        r = intent("Find seafood nearby")
        assert r.protein_type == "seafood"

    def test_lamb(self):
        r = intent("Any good lamb dishes?")
        assert r.protein_type == "lamb"

    def test_shrimp(self):
        r = intent("Show shrimp dishes")
        assert r.protein_type == "shrimp"

    def test_grilled_chicken(self):
        r = intent("I want grilled chicken")
        assert r.protein_type == "chicken"

    def test_steak(self):
        r = intent("Find steak near me")
        assert r.protein_type == "steak"

    def test_crab(self):
        r = intent("Show crab dishes")
        assert r.protein_type == "crab"

    def test_salmon(self):
        r = intent("Order salmon")
        assert r.protein_type == "salmon"

    def test_wings(self):
        r = intent("Chicken wings nearby")
        assert r.protein_type == "chicken"
        assert r.dish_name and "wings" in r.dish_name


# ═══════════════════════════════════════════════════════════════════════════
# 🥗 DIET BASED (10 tests)
# ═══════════════════════════════════════════════════════════════════════════

class TestDietBased:
    def test_vegetarian(self):
        r = intent("Show vegetarian food")
        assert r.diet_type == "vegetarian"

    def test_vegan(self):
        r = intent("Find vegan meals")
        assert r.diet_type == "vegan"

    def test_keto(self):
        r = intent("Keto friendly food near me")
        assert r.diet_type == "keto"

    def test_gluten_free(self):
        r = intent("Gluten free restaurants")
        assert r.diet_type == "gluten-free"

    def test_low_carb(self):
        r = intent("Low carb dinner ideas")
        assert r.diet_type == "low-carb"

    def test_healthy(self):
        r = intent("Healthy meals nearby")
        assert r.diet_type == "healthy"

    def test_dairy_free(self):
        r = intent("Dairy free options")
        assert r.diet_type == "dairy-free"

    def test_high_protein(self):
        r = intent("High protein meals")
        assert r.diet_type == "high-protein"

    def test_plant_based(self):
        r = intent("Plant based food")
        assert r.diet_type == "plant-based"

    def test_paleo(self):
        r = intent("Paleo friendly meals")
        assert r.diet_type == "paleo"


# ═══════════════════════════════════════════════════════════════════════════
# 💰 BUDGET BASED (10 tests)
# ═══════════════════════════════════════════════════════════════════════════

class TestBudgetBased:
    def test_under_10(self):
        r = intent("Show food under $10")
        assert r.price_max == 10

    def test_cheap_meals(self):
        r = intent("Cheap meals near me")
        assert r.dish_name is None or r.recommendation_mode

    def test_dinner_under_20(self):
        r = intent("Dinner under $20")
        assert r.price_max == 20

    def test_feed_3_under_30(self):
        r = intent("Feed 3 people under $30")
        assert r.people_count == 3
        assert r.budget_total == 30

    def test_feed_5_under_50(self):
        r = intent("Feed 5 people under $50")
        assert r.people_count == 5
        assert r.budget_total == 50

    def test_best_value(self):
        r = intent("Best value meals nearby")
        # Should have recommendation mode or dish search
        assert r.recommendation_mode or r.dish_name is not None

    def test_affordable_lunch(self):
        r = intent("Affordable lunch options")
        assert r.meal_type == "lunch" or r.recommendation_mode

    def test_budget_dinner(self):
        r = intent("Budget friendly dinner")
        assert r.meal_type == "dinner" or r.recommendation_mode

    def test_cheap_pizza(self):
        r = intent("Cheap pizza nearby")
        assert r.dish_name == "pizza"

    def test_best_for_15(self):
        r = intent("Best meal for $15")
        assert r.price_max == 15


# ═══════════════════════════════════════════════════════════════════════════
# 👨‍👩‍👧 GROUP ORDERS (10 tests)
# ═══════════════════════════════════════════════════════════════════════════

class TestGroupOrders:
    def test_feed_4(self):
        r = intent("Feed 4 people")
        assert r.people_count == 4

    def test_dinner_for_6(self):
        r = intent("Order dinner for 6 people")
        assert r.people_count == 6

    def test_family_of_5(self):
        r = intent("Food for family of 5")
        assert r.people_count == 5

    def test_party_for_8(self):
        r = intent("Party food for 8 people")
        assert r.people_count == 8

    def test_snacks_for_3(self):
        r = intent("Snacks for 3 friends")
        assert r.people_count == 3

    def test_dinner_team(self):
        r = intent("Dinner for my team")
        assert r.meal_type == "dinner"

    def test_small_gathering(self):
        r = intent("Food for small gathering")
        # Should trigger recommendation or some flag
        assert r.recommendation_mode or r.dish_name is not None

    def test_group_food(self):
        r = intent("Order food for group")
        assert r.recommendation_mode or r.dish_name is not None

    def test_combo_4(self):
        r = intent("Best combo for 4 people")
        assert r.people_count == 4

    def test_group_meal_ideas(self):
        r = intent("Group meal ideas")
        assert r.recommendation_mode


# ═══════════════════════════════════════════════════════════════════════════
# ⏱ TIME BASED (10 tests)
# ═══════════════════════════════════════════════════════════════════════════

class TestTimeBased:
    def test_quick_lunch(self):
        r = intent("Quick lunch nearby")
        assert r.meal_type == "lunch"

    def test_food_now(self):
        r = intent("Food available now")
        assert r.open_now is True

    def test_late_night(self):
        r = intent("Late night food")
        assert r.recommendation_mode or r.dish_name is not None

    def test_breakfast(self):
        r = intent("Breakfast near me")
        assert r.meal_type == "breakfast"

    def test_lunch_options(self):
        r = intent("Lunch options nearby")
        assert r.meal_type == "lunch"

    def test_dinner_options(self):
        r = intent("Dinner options near me")
        assert r.meal_type == "dinner"

    def test_open_now(self):
        r = intent("Restaurants open now")
        assert r.open_now is True


# ═══════════════════════════════════════════════════════════════════════════
# ⭐ RATING BASED (10 tests)
# ═══════════════════════════════════════════════════════════════════════════

class TestRatingBased:
    def test_top_rated(self):
        r = intent("Top rated restaurants near me")
        assert r.rating_min is not None and r.rating_min >= 4.0

    def test_best_pizza(self):
        r = intent("Best pizza in town")
        assert r.dish_name == "pizza"

    def test_highly_rated_sushi(self):
        r = intent("Highly rated sushi")
        assert r.dish_name and "sushi" in r.dish_name

    def test_popular_burgers(self):
        r = intent("Popular burgers nearby")
        assert r.dish_name and "burgers" in r.dish_name

    def test_best_indian(self):
        r = intent("Best Indian restaurant")
        assert r.cuisine == "Indian"

    def test_4_star(self):
        r = intent("4 star restaurants nearby")
        assert r.rating_min == 4.0

    def test_best_tacos(self):
        r = intent("Best tacos near me")
        assert r.dish_name == "tacos"

    def test_most_popular_ramen(self):
        r = intent("Most popular ramen")
        assert r.dish_name == "ramen"


# ═══════════════════════════════════════════════════════════════════════════
# 😋 MOOD / CRAVING (10 tests)
# ═══════════════════════════════════════════════════════════════════════════

class TestMoodCraving:
    def test_spicy(self):
        r = intent("I feel like eating something spicy")
        assert r.spice_level == "spicy"

    def test_comfort_food(self):
        r = intent("I want comfort food")
        assert r.recommendation_mode or r.dish_name is not None

    def test_craving_pizza(self):
        r = intent("I am craving pizza")
        assert r.dish_name == "pizza"

    def test_something_sweet(self):
        r = intent("Something sweet")
        assert r.recommendation_mode or r.dish_name is not None

    def test_something_light(self):
        r = intent("Something light to eat")
        assert r.recommendation_mode

    def test_something_cheesy(self):
        r = intent("Something cheesy")
        assert r.recommendation_mode or r.dish_name is not None

    def test_noodles(self):
        r = intent("I feel like eating noodles")
        assert r.dish_name == "noodles"


# ═══════════════════════════════════════════════════════════════════════════
# 🤖 DISCOVERY MODE (12 tests)
# ═══════════════════════════════════════════════════════════════════════════

class TestDiscoveryMode:
    def test_dont_know(self):
        r = intent("I don't know what to eat")
        assert r.recommendation_mode is True

    def test_surprise_me(self):
        r = intent("Surprise me with something good")
        assert r.recommendation_mode is True

    def test_recommend_dinner(self):
        r = intent("Recommend dinner")
        assert r.recommendation_mode is True

    def test_what_should_eat(self):
        r = intent("What should I eat tonight?")
        assert r.recommendation_mode is True

    def test_suggest_tasty(self):
        r = intent("Suggest something tasty")
        assert r.recommendation_mode is True

    def test_dinner_ideas(self):
        r = intent("Give me dinner ideas")
        assert r.recommendation_mode is True

    def test_popular_dishes(self):
        r = intent("Show popular dishes nearby")
        assert r.recommendation_mode is True

    def test_recommend_cheap(self):
        r = intent("Recommend something cheap")
        assert r.recommendation_mode is True

    def test_best_meal_now(self):
        r = intent("Best meal right now")
        assert r.recommendation_mode

    def test_pick_something(self):
        r = intent("Pick something for me")
        assert r.recommendation_mode is True

    def test_i_am_hungry(self):
        r = intent("I am hungry")
        assert r.recommendation_mode is True

    def test_suggest_food(self):
        r = intent("Suggest some best food near by")
        assert r.recommendation_mode is True


# ═══════════════════════════════════════════════════════════════════════════
# 🍽 OCCASION (8 tests)
# ═══════════════════════════════════════════════════════════════════════════

class TestOccasion:
    def test_date_night(self):
        r = intent("Food for date night")
        assert r.occasion and "date" in r.occasion

    def test_birthday(self):
        r = intent("Birthday dinner ideas")
        assert r.occasion == "birthday"

    def test_family_dinner(self):
        r = intent("Family dinner ideas")
        assert r.occasion and "family" in r.occasion

    def test_game_night(self):
        r = intent("Game night snacks")
        assert r.occasion and "game" in r.occasion

    def test_movie_night(self):
        r = intent("Food for movie night")
        assert r.occasion and "movie" in r.occasion


# ═══════════════════════════════════════════════════════════════════════════
# 🧠 MESSY HUMAN LANGUAGE (slang, typos, casual) (10 tests)
# ═══════════════════════════════════════════════════════════════════════════

class TestMessyHumanLanguage:
    def test_hungry_bro(self):
        r = intent("I'm hungry bro give me cheap pizza")
        assert r.dish_name == "pizza"

    def test_need_food_asap(self):
        r = intent("need food asap")
        assert r.recommendation_mode is True

    def test_spicy_chicken_pls(self):
        r = intent("spicy chicken pls")
        assert r.protein_type == "chicken"
        assert r.spice_level == "spicy"

    def test_under_10_bucks(self):
        r = intent("something good under 10 bucks")
        assert r.price_max == 10

    def test_food_3_people_quick(self):
        r = intent("food for 3 people quick")
        assert r.people_count == 3

    def test_gimme_pizza(self):
        r = intent("gimme pizza")
        assert r.dish_name == "pizza"

    def test_wanna_eat_biryani(self):
        r = intent("wanna eat biryani")
        assert r.dish_name == "biryani"

    def test_any_good_samosa(self):
        r = intent("any best samosa near by")
        assert r.dish_name == "samosa"

    def test_show_me_naan(self):
        r = intent("show me naan")
        assert r.dish_name == "naan"

    def test_i_want_dosa(self):
        r = intent("i want dosa please")
        assert r.dish_name == "dosa"


# ═══════════════════════════════════════════════════════════════════════════
# 🔀 MULTI-INTENT (COMPLEX) QUERIES (10 tests)
# ═══════════════════════════════════════════════════════════════════════════

class TestMultiIntent:
    def test_spicy_chicken_ramen_under_15(self):
        r = intent("I want spicy chicken ramen under $15")
        assert r.dish_name and "ramen" in r.dish_name
        assert r.protein_type == "chicken"
        assert r.spice_level == "spicy"
        assert r.price_max == 15

    def test_vegetarian_chinese(self):
        r = intent("Show me vegetarian Chinese food near me open now")
        assert r.cuisine == "Chinese"
        assert r.diet_type == "vegetarian"
        assert r.open_now is True

    def test_indian_under_50_5_people(self):
        r = intent("Feed 5 people with Indian food under $50")
        assert r.cuisine == "Indian"
        assert r.people_count == 5
        assert r.budget_total == 50

    def test_cheap_italian_pizza(self):
        r = intent("Cheap Italian pizza under $10")
        assert r.dish_name == "pizza"
        assert r.cuisine == "Italian"
        assert r.price_max == 10

    def test_healthy_chicken_lunch(self):
        r = intent("Healthy chicken lunch options")
        assert r.protein_type == "chicken"
        assert r.diet_type == "healthy"
        assert r.meal_type == "lunch"

    def test_vegan_thai(self):
        r = intent("Vegan Thai food nearby")
        assert r.cuisine == "Thai"
        assert r.diet_type == "vegan"

    def test_best_beef_burgers_under_15(self):
        r = intent("Best beef burgers under $15")
        assert r.protein_type == "beef"
        assert r.dish_name and "burgers" in r.dish_name
        assert r.price_max == 15

    def test_4_star_japanese(self):
        r = intent("4 star Japanese restaurants")
        assert r.cuisine == "Japanese"
        assert r.rating_min == 4.0

    def test_spicy_korean_chicken(self):
        r = intent("Spicy Korean chicken")
        assert r.cuisine == "Korean"
        assert r.protein_type == "chicken"
        assert r.spice_level == "spicy"

    def test_gluten_free_italian(self):
        r = intent("Gluten free Italian food")
        assert r.cuisine == "Italian"
        assert r.diet_type == "gluten-free"

# ═══════════════════════════════════════════════════════════════════════════
# 🍽 MEAL PLANNER (15 tests)
# ═══════════════════════════════════════════════════════════════════════════

class TestMealPlanner:
    def test_plan_meals_week(self):
        r = intent("Plan my meals for the week under $120")
        assert r.meal_plan_mode is True
        assert r.plan_days == 5
        assert r.price_max == 120 or r.budget_total == 120

    def test_weekly_meal_plan(self):
        r = intent("Weekly meal plan under $80")
        assert r.meal_plan_mode is True
        assert r.plan_days == 5
        assert r.price_max == 80

    def test_5_day_meal_plan(self):
        r = intent("5 day meal plan")
        assert r.meal_plan_mode is True
        assert r.plan_days == 5

    def test_3_day_plan(self):
        r = intent("3 day meal plan under $50")
        assert r.meal_plan_mode is True
        assert r.plan_days == 3
        assert r.price_max == 50

    def test_full_week(self):
        r = intent("Create meal plan for full week")
        assert r.meal_plan_mode is True
        assert r.plan_days == 7

    def test_plan_meals_for_week(self):
        r = intent("plan meals for this week")
        assert r.meal_plan_mode is True
        assert r.plan_days == 5

    def test_weekly_dinner_plan(self):
        r = intent("weekly dinner plan under $80")
        assert r.meal_plan_mode is True
        assert r.meal_type == "dinner"

    def test_healthy_lunch_plan(self):
        r = intent("healthy lunch plan for 5 days")
        assert r.meal_plan_mode is True
        assert r.plan_days == 5
        assert r.diet_type == "healthy"

    def test_vegetarian_plan(self):
        r = intent("vegetarian meal plan for 3 days")
        assert r.meal_plan_mode is True
        assert r.plan_days == 3
        assert r.diet_type == "vegetarian"

    def test_create_food_plan(self):
        r = intent("create my food plan for the week")
        assert r.meal_plan_mode is True

    def test_generate_meal_plan(self):
        r = intent("generate meal plan budget $100")
        assert r.meal_plan_mode is True
        assert r.price_max == 100

    def test_build_meal_plan(self):
        r = intent("build a meal plan for 4 days")
        assert r.meal_plan_mode is True
        assert r.plan_days == 4

    def test_make_food_plan(self):
        r = intent("make a food plan under $60")
        assert r.meal_plan_mode is True
        assert r.price_max == 60

    def test_daily_meal_plan(self):
        r = intent("daily meal plan under $20")
        assert r.meal_plan_mode is True
        assert r.price_max == 20

    def test_plan_meals_has_variety(self):
        r = intent("plan my meals for the week")
        assert r.meal_plan_mode is True
        assert r.variety_required is True

# ═══════════════════════════════════════════════════════════════════════════
# 🛡 EDGE CASES & REGRESSION (15 tests)
# ═══════════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    """Edge cases that should not crash the intent extractor."""

    def test_empty_string(self):
        r = intent("")
        assert r.has_search_criteria() is False

    def test_whitespace_only(self):
        r = intent("   ")
        assert r.has_search_criteria() is False

    def test_single_char(self):
        r = intent("x")
        assert r is not None  # Should not crash

    def test_emoji_only(self):
        r = intent("🍕🍔🌮")
        assert r is not None  # Should not crash

    def test_very_long_query(self):
        long_text = "I want pizza " * 100  # 1300 chars
        r = intent(long_text)
        assert "pizza" in r.dish_name

    def test_special_characters(self):
        r = intent("pizza @#$%^&*()")
        assert r is not None

    def test_numbers_only(self):
        r = intent("12345")
        assert r is not None

    def test_html_injection(self):
        r = intent("<script>alert('xss')</script>")
        assert r is not None

    def test_sql_injection_attempt(self):
        r = intent("'; DROP TABLE users; --")
        assert r is not None

    def test_mixed_case(self):
        r = intent("CHICKEN BIRYANI")
        assert r.protein_type == "chicken"

    def test_extra_whitespace(self):
        r = intent("  I   want   pizza   ")
        assert r.dish_name == "pizza"

    def test_ambiguous_multi_intent(self):
        """Query that could be both a dish search AND a recommendation."""
        r = intent("suggest the best biryani under $15")
        assert r.recommendation_mode is True or r.dish_name is not None

    def test_price_without_dollar(self):
        r = intent("pizza under 10")
        assert r.dish_name == "pizza"
        # May or may not extract price without $ — just shouldn't crash

    def test_budget_with_comma(self):
        r = intent("food for 5 under $1,000")
        assert r is not None

    def test_mixed_language_hint(self):
        """Hindi-English mix: 'mujhe biryani chahiye'."""
        r = intent("mujhe biryani chahiye")
        assert r.dish_name is not None and "biryani" in r.dish_name


# ═══════════════════════════════════════════════════════════════════════════
# Run
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

