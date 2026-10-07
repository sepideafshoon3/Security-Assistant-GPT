# ui-console

React + TypeScript + Vite frontend for Security Assistant GPT. See the
[root README](../README.md) for the full setup.

```bash
cp .env.example .env     # VITE_API_BASE_URL=http://127.0.0.1:8000
npm ci
npm run dev              # http://localhost:5173
```

| Script                            | What it does                                |
| --------------------------------- | ------------------------------------------- |
| `npm run dev`                     | Dev server with hot reload                  |
| `npm run build`                   | Type-check (`tsc -b`) and bundle to `dist/` |
| `npm run lint`                    | ESLint                                      |
| `npm run format` / `format:check` | Prettier (write / check only)               |
| `npm run preview`                 | Serve the production build locally          |

`VITE_API_BASE_URL` is read at **build time** (Vite has no runtime config), so after
changing it you must rebuild. The Docker image takes it as a build argument; see
`Dockerfile`.
