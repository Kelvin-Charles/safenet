-- Migration: Add bandwidth limit columns to plans and radusers tables
-- Run this script if you're upgrading from an older version

USE radius;

-- Add bandwidth columns to plans table
ALTER TABLE plans 
ADD COLUMN IF NOT EXISTS upload_speed VARCHAR(32) DEFAULT NULL,
ADD COLUMN IF NOT EXISTS download_speed VARCHAR(32) DEFAULT NULL,
ADD COLUMN IF NOT EXISTS data_cap BIGINT(20) DEFAULT NULL;

-- Add bandwidth columns to radusers table
ALTER TABLE radusers 
ADD COLUMN IF NOT EXISTS upload_speed VARCHAR(32) DEFAULT NULL,
ADD COLUMN IF NOT EXISTS download_speed VARCHAR(32) DEFAULT NULL,
ADD COLUMN IF NOT EXISTS data_cap BIGINT(20) DEFAULT NULL;

-- Verify columns were added
SELECT 'Migration completed successfully' AS status;

