CREATE TABLE public.tde_preserved_probe (
    id integer PRIMARY KEY,
    secret text NOT NULL
);

INSERT INTO public.tde_preserved_probe (id, secret)
VALUES (1, 'SPS_TDE_EXISTING_DATA_SENTINEL_7f4cdb1a');
