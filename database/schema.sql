-- SafeNet RADIUS Manager Database Schema
-- Multi-Vendor FreeRADIUS Support

-- Set character set
SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- ============================================
-- FreeRADIUS Standard Tables
-- ============================================

-- User authentication data
CREATE TABLE IF NOT EXISTS radcheck (
    id INT(11) UNSIGNED NOT NULL AUTO_INCREMENT,
    username VARCHAR(64) NOT NULL DEFAULT '',
    attribute VARCHAR(64) NOT NULL DEFAULT '',
    op CHAR(2) NOT NULL DEFAULT '==',
    value VARCHAR(253) NOT NULL DEFAULT '',
    PRIMARY KEY (id),
    KEY username (username(32))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- User reply attributes
CREATE TABLE IF NOT EXISTS radreply (
    id INT(11) UNSIGNED NOT NULL AUTO_INCREMENT,
    username VARCHAR(64) NOT NULL DEFAULT '',
    attribute VARCHAR(64) NOT NULL DEFAULT '',
    op CHAR(2) NOT NULL DEFAULT '=',
    value VARCHAR(253) NOT NULL DEFAULT '',
    PRIMARY KEY (id),
    KEY username (username(32))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Group check attributes
CREATE TABLE IF NOT EXISTS radgroupcheck (
    id INT(11) UNSIGNED NOT NULL AUTO_INCREMENT,
    groupname VARCHAR(64) NOT NULL DEFAULT '',
    attribute VARCHAR(64) NOT NULL DEFAULT '',
    op CHAR(2) NOT NULL DEFAULT '==',
    value VARCHAR(253) NOT NULL DEFAULT '',
    PRIMARY KEY (id),
    KEY groupname (groupname(32))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Group reply attributes
CREATE TABLE IF NOT EXISTS radgroupreply (
    id INT(11) UNSIGNED NOT NULL AUTO_INCREMENT,
    groupname VARCHAR(64) NOT NULL DEFAULT '',
    attribute VARCHAR(64) NOT NULL DEFAULT '',
    op CHAR(2) NOT NULL DEFAULT '=',
    value VARCHAR(253) NOT NULL DEFAULT '',
    priority INT(11) NOT NULL DEFAULT 0,
    PRIMARY KEY (id),
    KEY groupname (groupname(32))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- User to group mapping
CREATE TABLE IF NOT EXISTS radusergroup (
    id INT(11) UNSIGNED NOT NULL AUTO_INCREMENT,
    username VARCHAR(64) NOT NULL DEFAULT '',
    groupname VARCHAR(64) NOT NULL DEFAULT '',
    priority INT(11) NOT NULL DEFAULT 1,
    PRIMARY KEY (id),
    KEY username (username(32))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Accounting data
CREATE TABLE IF NOT EXISTS radacct (
    radacctid BIGINT(21) NOT NULL AUTO_INCREMENT,
    acctsessionid VARCHAR(64) NOT NULL DEFAULT '',
    acctuniqueid VARCHAR(32) NOT NULL DEFAULT '',
    username VARCHAR(64) NOT NULL DEFAULT '',
    groupname VARCHAR(64) NOT NULL DEFAULT '',
    realm VARCHAR(64) DEFAULT '',
    nasipaddress VARCHAR(15) NOT NULL DEFAULT '',
    nasportid VARCHAR(32) DEFAULT NULL,
    nasporttype VARCHAR(32) DEFAULT NULL,
    acctstarttime DATETIME NULL DEFAULT NULL,
    acctupdatetime DATETIME NULL DEFAULT NULL,
    acctstoptime DATETIME NULL DEFAULT NULL,
    acctinterval INT(12) DEFAULT NULL,
    acctsessiontime INT(12) UNSIGNED DEFAULT NULL,
    acctauthentic VARCHAR(32) DEFAULT NULL,
    connectinfo_start VARCHAR(50) DEFAULT NULL,
    connectinfo_stop VARCHAR(50) DEFAULT NULL,
    acctinputoctets BIGINT(20) DEFAULT NULL,
    acctoutputoctets BIGINT(20) DEFAULT NULL,
    calledstationid VARCHAR(50) NOT NULL DEFAULT '',
    callingstationid VARCHAR(50) NOT NULL DEFAULT '',
    acctterminatecause VARCHAR(32) NOT NULL DEFAULT '',
    servicetype VARCHAR(32) DEFAULT NULL,
    framedprotocol VARCHAR(32) DEFAULT NULL,
    framedipaddress VARCHAR(15) NOT NULL DEFAULT '',
    PRIMARY KEY (radacctid),
    UNIQUE KEY acctuniqueid (acctuniqueid),
    KEY username (username),
    KEY framedipaddress (framedipaddress),
    KEY acctsessionid (acctsessionid),
    KEY acctstarttime (acctstarttime),
    KEY acctstoptime (acctstoptime),
    KEY nasipaddress (nasipaddress)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Post-auth logging
CREATE TABLE IF NOT EXISTS radpostauth (
    id INT(11) NOT NULL AUTO_INCREMENT,
    username VARCHAR(64) NOT NULL DEFAULT '',
    pass VARCHAR(64) NOT NULL DEFAULT '',
    reply VARCHAR(32) NOT NULL DEFAULT '',
    authdate TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY username (username),
    KEY authdate (authdate)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- NAS (Network Access Servers)
CREATE TABLE IF NOT EXISTS nas (
    id INT(10) NOT NULL AUTO_INCREMENT,
    nasname VARCHAR(128) NOT NULL,
    shortname VARCHAR(32) NOT NULL,
    type VARCHAR(30) NOT NULL DEFAULT 'other',
    ports INT(5) DEFAULT NULL,
    secret VARCHAR(60) NOT NULL DEFAULT 'secret',
    server VARCHAR(64) DEFAULT NULL,
    community VARCHAR(50) DEFAULT NULL,
    description VARCHAR(200) DEFAULT NULL,
    vendor VARCHAR(32) DEFAULT 'standard',
    is_active TINYINT(1) DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY nasname (nasname),
    KEY shortname (shortname)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ============================================
-- Application-Specific Tables
-- ============================================

-- Admin users
CREATE TABLE IF NOT EXISTS admins (
    id INT(11) NOT NULL AUTO_INCREMENT,
    username VARCHAR(64) NOT NULL,
    email VARCHAR(120) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    is_active TINYINT(1) DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_login DATETIME DEFAULT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY username (username),
    UNIQUE KEY email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Plans (Service plans/groups)
CREATE TABLE IF NOT EXISTS plans (
    id INT(11) NOT NULL AUTO_INCREMENT,
    name VARCHAR(64) NOT NULL,
    description TEXT,
    vendor VARCHAR(32) DEFAULT 'standard',
    is_active TINYINT(1) DEFAULT 1,
    upload_speed VARCHAR(32) DEFAULT NULL,
    download_speed VARCHAR(32) DEFAULT NULL,
    data_cap BIGINT(20) DEFAULT NULL,
    data_cap_period VARCHAR(10) DEFAULT 'monthly',
    last_reset DATETIME DEFAULT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Plan attributes (vendor-agnostic)
CREATE TABLE IF NOT EXISTS plan_attributes (
    id INT(11) NOT NULL AUTO_INCREMENT,
    plan_id INT(11) NOT NULL,
    attribute VARCHAR(64) NOT NULL,
    op VARCHAR(2) NOT NULL DEFAULT ':=',
    value VARCHAR(253) NOT NULL,
    vendor VARCHAR(32) DEFAULT NULL,
    priority INT(11) DEFAULT 0,
    PRIMARY KEY (id),
    KEY plan_id (plan_id),
    FOREIGN KEY (plan_id) REFERENCES plans(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Extended user information
CREATE TABLE IF NOT EXISTS radusers (
    id INT(11) NOT NULL AUTO_INCREMENT,
    username VARCHAR(64) NOT NULL,
    plan_id INT(11) DEFAULT NULL,
    is_active TINYINT(1) DEFAULT 1,
    expires_at DATETIME DEFAULT NULL,
    notes TEXT,
    upload_speed VARCHAR(32) DEFAULT NULL,
    download_speed VARCHAR(32) DEFAULT NULL,
    data_cap BIGINT(20) DEFAULT NULL,
    data_cap_period VARCHAR(10) DEFAULT 'monthly',
    last_reset DATETIME DEFAULT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY username (username),
    KEY plan_id (plan_id),
    FOREIGN KEY (plan_id) REFERENCES plans(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ============================================
-- Indexes for Performance
-- ============================================

-- Additional indexes for accounting queries
CREATE INDEX idx_radacct_username_start ON radacct(username, acctstarttime);
CREATE INDEX idx_radacct_nas_start ON radacct(nasipaddress, acctstarttime);

-- ============================================
-- Sample Data (Optional)
-- ============================================

-- Insert default NAS for testing (localhost)
INSERT IGNORE INTO nas (nasname, shortname, type, secret, vendor, description) 
VALUES ('127.0.0.1', 'localhost', 'other', 'testing123', 'standard', 'Local testing');

-- ============================================
-- Views for Reporting (Optional)
-- ============================================

-- Active sessions view
CREATE OR REPLACE VIEW active_sessions AS
SELECT 
    radacctid,
    username,
    nasipaddress,
    framedipaddress,
    acctstarttime,
    TIMESTAMPDIFF(SECOND, acctstarttime, NOW()) as duration_seconds,
    acctinputoctets,
    acctoutputoctets,
    (acctinputoctets + acctoutputoctets) as total_octets
FROM radacct
WHERE acctstoptime IS NULL
ORDER BY acctstarttime DESC;

-- User data usage summary
CREATE OR REPLACE VIEW user_data_usage AS
SELECT 
    username,
    COUNT(*) as session_count,
    SUM(acctsessiontime) as total_time_seconds,
    SUM(acctinputoctets) as total_input_octets,
    SUM(acctoutputoctets) as total_output_octets,
    SUM(acctinputoctets + acctoutputoctets) as total_octets,
    MAX(acctstarttime) as last_session
FROM radacct
GROUP BY username
ORDER BY total_octets DESC;

SET FOREIGN_KEY_CHECKS = 1;

-- End of schema


