-- Runs once, when the data volume is first created.
-- A separate database for the test suite, so tests can truncate tables freely.
CREATE DATABASE documind_test OWNER documind;
