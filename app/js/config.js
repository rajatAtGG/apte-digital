// Replaced by scripts/build-app.mjs in dist/ with the hashed database name,
// its size and the app version. These defaults are only for reference.
export const DB_URL = 'data/apte.sqlite.gz';
export const DB_GZ_BYTES = 12_000_000;
export const APP_VERSION = 'dev';
// Optional: the database split into several files, fetched in order and
// joined (used where the host limits file size). Empty = just DB_URL.
export const DB_PARTS = [];
