-- Restore the schema that the shared FeedMer database must have for orders.
--
-- Why this is needed (both points are visible in the FeedMer repo, which is NOT modified):
--   * FeedMer `migrations` (15.04.2022) declares
--         items.id integer NOT NULL GENERATED ALWAYS AS IDENTITY
--     plus PRIMARY KEY (id) and FOREIGN KEY (pk_order) REFERENCES orders(pk_orders);
--   * FeedMer code always inserts orders/items WITHOUT ids and reads the order id back:
--         DBlib.js saveOrder  -> INSERT INTO orders (...) RETURNING pk_orders
--         DBlib.js addItem    -> INSERT INTO items (item_name, ...) VALUES (...)
--     so the database has to assign both `orders.pk_orders` and `items.id`.
--
-- In the `testing` database those tables came from a copy: no PK, no FK, no identity
-- and no sequence for pk_orders, which makes both this bot and FeedMer itself fail on
-- insert. This script is idempotent, so it is safe to re-run.
--
--   psql -h localhost -U postgres -d testing -v ON_ERROR_STOP=1 -f scripts/fix_shared_orders_schema.sql
BEGIN;

-- orders.pk_orders: sequence + default (the serial equivalent), owned by the table owner
CREATE SEQUENCE IF NOT EXISTS public.orders_pk_orders_seq;
DO $do$
DECLARE table_owner text;
BEGIN
  SELECT pg_get_userbyid(relowner) INTO table_owner
  FROM pg_class WHERE oid = 'public.orders'::regclass;
  EXECUTE format('ALTER SEQUENCE public.orders_pk_orders_seq OWNER TO %I', table_owner);
  EXECUTE 'ALTER SEQUENCE public.orders_pk_orders_seq OWNED BY public.orders.pk_orders';
END
$do$;
ALTER TABLE public.orders
  ALTER COLUMN pk_orders SET DEFAULT nextval('public.orders_pk_orders_seq'::regclass);
SELECT setval('public.orders_pk_orders_seq',
              (SELECT COALESCE(MAX(pk_orders), 0) + 1 FROM public.orders), false);

-- items.id: the identity declared in the migrations, starting above the current max
DO $do$
DECLARE next_item_id bigint;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_attribute
                 WHERE attrelid = 'public.items'::regclass
                   AND attname = 'id'
                   AND attidentity <> '') THEN
    SELECT COALESCE(MAX(id), 0) + 1 INTO next_item_id FROM public.items;
    EXECUTE format(
      'ALTER TABLE public.items ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (START WITH %s)',
      next_item_id);
  END IF;
END
$do$;

-- keys declared in the migrations but missing in a copied database
DO $do$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conrelid = 'public.orders'::regclass AND contype = 'p') THEN
    ALTER TABLE public.orders ADD CONSTRAINT orders_pkey PRIMARY KEY (pk_orders);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conrelid = 'public.items'::regclass AND contype = 'p') THEN
    ALTER TABLE public.items ADD CONSTRAINT id PRIMARY KEY (id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'items_pk_order_fkey') THEN
    ALTER TABLE public.items ADD CONSTRAINT items_pk_order_fkey
      FOREIGN KEY (pk_order) REFERENCES public.orders (pk_orders) MATCH SIMPLE;
  END IF;
END
$do$;

COMMIT;
