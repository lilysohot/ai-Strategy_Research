--
-- PostgreSQL database cluster dump
--

\restrict OyAYsxP6x1By6hC4QB3Ayg4JSsJ9Ow8CCXn8J7rSYAXJ6ckjrA5dvq85IHNstQ0

SET default_transaction_read_only = off;

SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;

--
-- Roles
--

CREATE ROLE postgres;
ALTER ROLE postgres WITH SUPERUSER INHERIT CREATEROLE CREATEDB LOGIN REPLICATION BYPASSRLS PASSWORD 'SCRAM-SHA-256$4096:B2TG0vuv4JZ545RIMJnhVg==$Nr+xKslZk/w4zBFVWd8XPBvYciWV2wn45pesup2eXuc=:f3+Sbs3goFZAOmZp87N4mh3pE5HX9WAYYj9Byx90/ag=';

--
-- User Configurations
--








\unrestrict OyAYsxP6x1By6hC4QB3Ayg4JSsJ9Ow8CCXn8J7rSYAXJ6ckjrA5dvq85IHNstQ0

--
-- PostgreSQL database cluster dump complete
--

