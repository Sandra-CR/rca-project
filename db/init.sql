CREATE TABLE tasks (
    id SERIAL PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    description TEXT DEFAULT '',
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

INSERT INTO tasks (title, description, is_active) VALUES
    ('Setup CI/CD pipeline', 'Configure GitHub Actions for automated testing', true),
    ('Write API documentation', 'Document all endpoints with examples', true),
    ('Fix login page CSS', 'Button alignment is off on mobile', false);
