--
-- PostgreSQL database cluster dump
--

\restrict QE5RHMrjISTiRXVz17r0g1OXg4Q36Xap5ipqZvMl4xco039Wiq3odft3hAzzmhU

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








\unrestrict QE5RHMrjISTiRXVz17r0g1OXg4Q36Xap5ipqZvMl4xco039Wiq3odft3hAzzmhU

--
-- PostgreSQL database cluster dump complete
--

