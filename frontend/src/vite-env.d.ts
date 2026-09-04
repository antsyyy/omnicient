/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL of the Omnicient API. Defaults to the dev-server proxy at /api. */
  readonly VITE_API_BASE?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
