-- Migration: Add data cap period and reset tracking to plans and radusers tables
-- Run this script to add daily/weekly/monthly period support and reset functionality

USE radius;

-- Add period and reset columns to plans table
ALTER TABLE plans 
ADD COLUMN IF NOT EXISTS data_cap_period VARCHAR(10) DEFAULT 'monthly',
ADD COLUMN IF NOT EXISTS last_reset DATETIME DEFAULT NULL;

-- Add period and reset columns to radusers table
ALTER TABLE radusers 
ADD COLUMN IF NOT EXISTS data_cap_period VARCHAR(10) DEFAULT 'monthly',
ADD COLUMN IF NOT EXISTS last_reset DATETIME DEFAULT NULL;

-- Set default period for existing records
UPDATE plans SET data_cap_period = 'monthly' WHERE data_cap_period IS NULL AND data_cap IS NOT NULL;
UPDATE radusers SET data_cap_period = 'monthly' WHERE data_cap_period IS NULL AND data_cap IS NOT NULL;

-- Verify columns were added
SELECT 'Migration completed successfully' AS status;

