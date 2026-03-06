create extension if not exists "pgcrypto";
create extension if not exists "vector";

create table if not exists users (
    id serial primary key,
    email varchar(255) unique not null,
    password_hash varchar(255) not null,
    created_at timestamp default now() not null
);

create table if not exists restaurants (
    id serial primary key,
    name varchar(200) not null,
    slug varchar(200) unique not null,
    description text,
    city varchar(120),
    is_active boolean default true not null,
    created_at timestamp default now() not null
);

create table if not exists menu_categories (
    id serial primary key,
    restaurant_id integer references restaurants(id) on delete cascade,
    name varchar(120) not null,
    sort_order integer default 0 not null
);

create table if not exists menu_items (
    id serial primary key,
    category_id integer references menu_categories(id) on delete cascade,
    name varchar(160) not null,
    description text,
    price_cents integer not null,
    is_available boolean default true not null
);

create table if not exists orders (
    id serial primary key,
    user_id integer references users(id) on delete cascade,
    restaurant_id integer references restaurants(id) on delete cascade,
    status varchar(40) default 'pending' not null,
    total_cents integer default 0 not null,
    created_at timestamp default now() not null
);

create table if not exists order_items (
    id serial primary key,
    order_id integer references orders(id) on delete cascade,
    menu_item_id integer references menu_items(id) on delete cascade,
    quantity integer not null,
    price_cents integer not null
);

create table if not exists chat_sessions (
    id serial primary key,
    user_id integer references users(id) on delete cascade,
    restaurant_id integer references restaurants(id) on delete set null,
    category_id integer references menu_categories(id) on delete set null,
    order_id integer references orders(id) on delete set null,
    status varchar(40) default 'active' not null,
    created_at timestamp default now() not null,
    updated_at timestamp default now() not null
);

create table if not exists chat_messages (
    id serial primary key,
    session_id integer references chat_sessions(id) on delete cascade,
    role varchar(40) not null,
    content text not null,
    created_at timestamp default now() not null
);

create table if not exists embeddings (
    id serial primary key,
    source_type varchar(80) not null,
    source_id integer not null,
    embedding vector(1536),
    created_at timestamp default now() not null
);

insert into restaurants (name, slug, description, city)
values
    ('Spice Garden', 'spice-garden', 'North Indian favorites', 'Bengaluru'),
    ('Sunset Diner', 'sunset-diner', 'Classic comfort food', 'Bengaluru'),
    ('Green Bowl', 'green-bowl', 'Healthy salads and bowls', 'Bengaluru')
on conflict do nothing;

insert into menu_categories (restaurant_id, name, sort_order)
values
    (1, 'Starters', 1),
    (1, 'Main Menu', 2),
    (1, 'Drinks', 3),
    (2, 'Starters', 1),
    (2, 'Main Menu', 2),
    (2, 'Desserts', 3),
    (3, 'Bowls', 1),
    (3, 'Soups', 2)
on conflict do nothing;

insert into menu_items (category_id, name, description, price_cents)
values
    (1, 'Paneer Tikka', 'Smoky cottage cheese skewers', 3200),
    (1, 'Veg Pakora', 'Crispy fritters', 1800),
    (2, 'Butter Naan', 'Soft buttery bread', 600),
    (2, 'Dal Makhani', 'Slow cooked lentils', 2500),
    (3, 'Mango Lassi', 'Sweet yogurt drink', 1400),
    (4, 'Garlic Fries', 'Crispy fries with garlic', 1700),
    (5, 'Grilled Chicken', 'Served with mashed potato', 3800),
    (6, 'Chocolate Cake', 'Warm cake slice', 2100),
    (7, 'Mediterranean Bowl', 'Quinoa, chickpeas, veggies', 2900),
    (8, 'Tomato Basil Soup', 'Creamy classic', 1500)
on conflict do nothing;
