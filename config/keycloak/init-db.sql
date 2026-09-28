-- Initialize databases for the full OSS AMFA stack.
-- This script runs as the 'keycloak' superuser on the 'keycloak' database.

-- Enable uuid-ossp in the keycloak database (used by the AMFA SPI changelog)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Create the AMFA engine database
SELECT 'CREATE DATABASE adaptive_mfa'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'adaptive_mfa')\gexec

GRANT ALL PRIVILEGES ON DATABASE adaptive_mfa TO keycloak;

-- Switch to adaptive_mfa and enable uuid-ossp there
\c adaptive_mfa
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
GRANT ALL ON SCHEMA public TO keycloak;
