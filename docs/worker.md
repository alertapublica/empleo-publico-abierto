# Worker de Cloudflare (cron de la ingesta)

El cron de GitHub se salta muchas ejecuciones, así que un worker (`worker/`, cuenta `empleo-publico`) lanza cada hora `actualizar.yml` con `workflow_dispatch`. Se despliega solo al fusionar en `main` (`.github/workflows/worker.yml`).

## Secretos

- **Del repo:** `CLOUDFLARE_API_TOKEN` (token acotado de despliegue), `CLOUDFLARE_ACCOUNT_ID` y `AVISOS_CLAVE` (ver [avisos](avisos.md)).
- **Del worker:** `GITHUB_TOKEN`, un token de grano fino solo para este repo con «Actions: read and write».

  ```bash
  cd worker && wrangler secret put GITHUB_TOKEN
  ```

## Tests

```bash
cd worker && node --test test/index.test.mjs
```
