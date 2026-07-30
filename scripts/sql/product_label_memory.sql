-- product_label_memory: aprendizaje etiqueta → producto Odoo
-- Corre en el schema del entorno (no mezclar staging/prod):
--   staging: sudataco_staging
--   prod:    sudataco_facturia
--
-- La app también hace CREATE TABLE IF NOT EXISTS al primer uso
-- (ensure_product_label_memory_table). Este SQL es para ops / review.

CREATE TABLE IF NOT EXISTS product_label_memory (
    id BIGINT NOT NULL AUTO_INCREMENT,
    company_id INT NOT NULL,
    template_id INT NOT NULL,
    partner_id INT NOT NULL,
    label_key VARCHAR(512) NOT NULL,
    product_id INT NOT NULL,
    source_process_id INT NULL,
    source_conversion_id INT NULL,
    updated_at DATETIME NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_product_label_memory
        (company_id, template_id, partner_id, label_key),
    KEY idx_product_label_memory_lookup
        (company_id, template_id, partner_id, label_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
