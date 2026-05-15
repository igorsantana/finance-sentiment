-- Option A publisher expansion (Empiricus, Levante, Petronotícias, Megawhat).
-- Idempotent — safe on databases that already ran 002.

INSERT INTO publishers (hostname, display_name, founded_year, ownership, homepage, affiliations) VALUES ('empiricus.com.br', 'Empiricus', 2013, 'Privada', 'https://www.empiricus.com.br', ARRAY[]::TEXT[]) ON CONFLICT (hostname) DO NOTHING;
INSERT INTO publishers (hostname, display_name, founded_year, ownership, homepage, affiliations) VALUES ('levanteideias.com.br', 'Levante Investimentos', 2018, 'Privada', 'https://www.levanteideias.com.br', ARRAY[]::TEXT[]) ON CONFLICT (hostname) DO NOTHING;
INSERT INTO publishers (hostname, display_name, founded_year, ownership, homepage, affiliations) VALUES ('petronoticias.com.br', 'Petronotícias', NULL, 'Privada', 'https://www.petronoticias.com.br', ARRAY[]::TEXT[]) ON CONFLICT (hostname) DO NOTHING;
INSERT INTO publishers (hostname, display_name, founded_year, ownership, homepage, affiliations) VALUES ('megawhat.com.br', 'Megawhat', NULL, 'Privada', 'https://www.megawhat.com.br', ARRAY[]::TEXT[]) ON CONFLICT (hostname) DO NOTHING;
