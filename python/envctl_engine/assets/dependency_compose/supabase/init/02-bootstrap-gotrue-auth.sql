CREATE SCHEMA IF NOT EXISTS auth;
ALTER ROLE postgres IN DATABASE postgres SET search_path = auth, public;
