-- Loan Ledger schema for MySQL 8 (AWS RDS), generated from the models.
-- Run against the database `lms`. Every statement is CREATE ... IF NOT EXISTS, so it is safe to re-run.
-- The app also creates these tables and adds missing columns on startup; this file is for doing it by hand.

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS audit_log (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	at DATETIME NOT NULL DEFAULT (now()), 
	username VARCHAR(64), 
	action VARCHAR(48) NOT NULL, 
	entity VARCHAR(32) NOT NULL, 
	entity_id VARCHAR(64), 
	detail TEXT, 
	PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS customers (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	external_ref VARCHAR(64), 
	name VARCHAR(160) NOT NULL, 
	mobile VARCHAR(20), 
	email VARCHAR(160), 
	pan VARCHAR(10), 
	address TEXT, 
	created_at DATETIME NOT NULL DEFAULT (now()), 
	PRIMARY KEY (id), 
	UNIQUE (external_ref)
);

CREATE TABLE IF NOT EXISTS loan_products (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	code VARCHAR(32) NOT NULL, 
	name VARCHAR(128) NOT NULL, 
	interest_method VARCHAR(16) NOT NULL, 
	default_rate NUMERIC(9, 4) NOT NULL, 
	min_tenure INTEGER NOT NULL, 
	max_tenure INTEGER NOT NULL, 
	min_amount NUMERIC(18, 2) NOT NULL, 
	max_amount NUMERIC(18, 2) NOT NULL, 
	apportion_mode VARCHAR(20) NOT NULL, 
	excess_mode VARCHAR(16) NOT NULL, 
	late_fee NUMERIC(18, 2) NOT NULL, 
	grace_days INTEGER NOT NULL, 
	bounce_charge NUMERIC(18, 2) NOT NULL, 
	foreclosure_fee_pct NUMERIC(9, 4) NOT NULL, 
	processing_fee_pct NUMERIC(9, 4) NOT NULL, 
	active BOOL NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (code)
);

CREATE TABLE IF NOT EXISTS rps_rows (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	loan_number VARCHAR(40) NOT NULL, 
	row_no INTEGER NOT NULL, 
	installment_no INTEGER, 
	due_date DATE, 
	emi_amount NUMERIC(18, 2), 
	principal_component NUMERIC(18, 2), 
	interest_component NUMERIC(18, 2), 
	paid_date DATE, 
	closing_balance NUMERIC(18, 2), 
	principal_paid NUMERIC(18, 2), 
	interest_paid NUMERIC(18, 2), 
	penalty_due NUMERIC(18, 2), 
	penalty_paid NUMERIC(18, 2), 
	penalty_waived NUMERIC(18, 2), 
	actual_charge NUMERIC(18, 2), 
	actual_charge_paid NUMERIC(18, 2), 
	source VARCHAR(12) NOT NULL, 
	payload TEXT NOT NULL, 
	created_by VARCHAR(64), 
	created_at DATETIME NOT NULL DEFAULT (now()), 
	PRIMARY KEY (id)
);
CREATE INDEX ix_rps_rows_loan ON rps_rows (loan_number);

CREATE TABLE IF NOT EXISTS rps_transactions (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	loan_number VARCHAR(40) NOT NULL, 
	txn_date DATE NOT NULL, 
	amount NUMERIC(18, 2) NOT NULL, 
	mode VARCHAR(16), 
	reference VARCHAR(64), 
	interest_applied NUMERIC(18, 2), 
	principal_applied NUMERIC(18, 2), 
	charges_applied NUMERIC(18, 2), 
	excess_held NUMERIC(18, 2), 
	created_by VARCHAR(64), 
	created_at DATETIME NOT NULL DEFAULT (now()), 
	PRIMARY KEY (id)
);
CREATE INDEX ix_rps_txn_loan ON rps_transactions (loan_number);

CREATE TABLE IF NOT EXISTS users (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	username VARCHAR(64) NOT NULL, 
	full_name VARCHAR(128) NOT NULL, 
	password_hash VARCHAR(256) NOT NULL, 
	`role` VARCHAR(16) NOT NULL, 
	active BOOL NOT NULL, 
	created_at DATETIME NOT NULL DEFAULT (now()), 
	PRIMARY KEY (id), 
	UNIQUE (username)
);

CREATE TABLE IF NOT EXISTS loans (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	loan_number VARCHAR(40) NOT NULL, 
	source VARCHAR(10) NOT NULL, 
	external_loan_id VARCHAR(64), 
	customer_id INTEGER NOT NULL, 
	product_id INTEGER, 
	principal NUMERIC(18, 2) NOT NULL, 
	annual_rate NUMERIC(9, 4) NOT NULL, 
	tenure_months INTEGER NOT NULL, 
	interest_method VARCHAR(16) NOT NULL, 
	disbursal_date DATE NOT NULL, 
	first_due_date DATE NOT NULL, 
	emi_amount NUMERIC(18, 2) NOT NULL, 
	processing_fee NUMERIC(18, 2) NOT NULL, 
	apportion_mode VARCHAR(20) NOT NULL, 
	excess_mode VARCHAR(16) NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	excess_amount NUMERIC(18, 2) NOT NULL, 
	opening_excess NUMERIC(18, 2) NOT NULL, 
	migration_cutoff DATE, 
	closed_date DATE, 
	loan_amount NUMERIC(18, 2), 
	last_due_date DATE, 
	stamp_duty NUMERIC(18, 2), 
	document_charges NUMERIC(18, 2), 
	insurance_amount NUMERIC(18, 2), 
	rsa_charge NUMERIC(18, 2), 
	bounce_charge NUMERIC(18, 2), 
	details TEXT, 
	created_by VARCHAR(64), 
	created_at DATETIME NOT NULL DEFAULT (now()), 
	PRIMARY KEY (id), 
	UNIQUE (loan_number), 
	UNIQUE (external_loan_id), 
	FOREIGN KEY(customer_id) REFERENCES customers (id), 
	FOREIGN KEY(product_id) REFERENCES loan_products (id)
);
CREATE INDEX ix_loans_source ON loans (source);
CREATE INDEX ix_loans_status ON loans (status);

CREATE TABLE IF NOT EXISTS installments (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	loan_id INTEGER NOT NULL, 
	installment_no INTEGER NOT NULL, 
	due_date DATE NOT NULL, 
	opening_balance NUMERIC(18, 2) NOT NULL, 
	principal_due NUMERIC(18, 2) NOT NULL, 
	interest_due NUMERIC(18, 2) NOT NULL, 
	opening_principal_paid NUMERIC(18, 2) NOT NULL, 
	opening_interest_paid NUMERIC(18, 2) NOT NULL, 
	principal_paid NUMERIC(18, 2) NOT NULL, 
	interest_paid NUMERIC(18, 2) NOT NULL, 
	status VARCHAR(12) NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (loan_id, installment_no), 
	FOREIGN KEY(loan_id) REFERENCES loans (id)
);
CREATE INDEX ix_inst_due ON installments (due_date);

CREATE TABLE IF NOT EXISTS repayments (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	loan_id INTEGER NOT NULL, 
	amount NUMERIC(18, 2) NOT NULL, 
	payment_date DATE NOT NULL, 
	mode VARCHAR(16) NOT NULL, 
	reference VARCHAR(64), 
	status VARCHAR(12) NOT NULL, 
	is_historical BOOL NOT NULL, 
	purpose VARCHAR(16) NOT NULL, 
	reversal_reason VARCHAR(255), 
	reversed_at DATETIME, 
	created_by VARCHAR(64), 
	created_at DATETIME NOT NULL DEFAULT (now()), 
	PRIMARY KEY (id), 
	FOREIGN KEY(loan_id) REFERENCES loans (id)
);
CREATE INDEX ix_rep_date ON repayments (payment_date);

CREATE TABLE IF NOT EXISTS charges (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	loan_id INTEGER NOT NULL, 
	installment_id INTEGER, 
	charge_type VARCHAR(24) NOT NULL, 
	charge_date DATE NOT NULL, 
	amount NUMERIC(18, 2) NOT NULL, 
	opening_paid NUMERIC(18, 2) NOT NULL, 
	paid NUMERIC(18, 2) NOT NULL, 
	waived NUMERIC(18, 2) NOT NULL, 
	description VARCHAR(255), 
	created_at DATETIME NOT NULL DEFAULT (now()), 
	PRIMARY KEY (id), 
	FOREIGN KEY(loan_id) REFERENCES loans (id), 
	FOREIGN KEY(installment_id) REFERENCES installments (id)
);

CREATE TABLE IF NOT EXISTS allocations (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	loan_id INTEGER NOT NULL, 
	repayment_id INTEGER, 
	installment_id INTEGER, 
	charge_id INTEGER, 
	component VARCHAR(12) NOT NULL, 
	amount NUMERIC(18, 2) NOT NULL, 
	applied_date DATE NOT NULL, 
	from_excess BOOL NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(loan_id) REFERENCES loans (id), 
	FOREIGN KEY(repayment_id) REFERENCES repayments (id), 
	FOREIGN KEY(installment_id) REFERENCES installments (id), 
	FOREIGN KEY(charge_id) REFERENCES charges (id)
);
CREATE INDEX ix_allocations_loan_id ON allocations (loan_id);
