-- Create reports table
CREATE TABLE IF NOT EXISTS reports (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    report_id VARCHAR NOT NULL UNIQUE,
    report_type VARCHAR NOT NULL,
    all_data TEXT NOT NULL,
    urgency VARCHAR,
    location VARCHAR,
    photo_id VARCHAR,
    user_id BIGINT,
    username VARCHAR,
    first_name VARCHAR,
    last_name VARCHAR,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

-- Create search function for reports
CREATE OR REPLACE FUNCTION search_reports(search_term TEXT)
RETURNS SETOF reports
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT *
    FROM reports
    WHERE 
        all_data ILIKE '%' || search_term || '%' OR
        report_id ILIKE '%' || search_term || '%' OR
        report_type ILIKE '%' || search_term || '%' OR
        location ILIKE '%' || search_term || '%';
END;
$$;

-- Add indexes for faster searching
CREATE INDEX IF NOT EXISTS idx_reports_report_id ON reports(report_id);
CREATE INDEX IF NOT EXISTS idx_reports_report_type ON reports(report_type);
CREATE INDEX IF NOT EXISTS idx_reports_all_data ON reports USING gin(to_tsvector('english', all_data));
CREATE INDEX IF NOT EXISTS idx_reports_user_id ON reports(user_id);
