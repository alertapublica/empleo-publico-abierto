# Worker de Cloudflare (cron de la ingesta)

El cron de GitHub se salta muchas ejecuciones, así que un worker (`worker/`, cuenta `empleo-publico`) lanza `actualizar.yml` con `workflow_dispatch`. Se despliega solo al fusionar en `main` (`.github/workflows/worker.yml`).

## Horario (hora de Madrid)

El cron se dispara a :07 y a :37 de cada hora (UTC) y `toca()` (`worker/src/index.js`) decide con la hora de Madrid si lanza, de modo que las franjas no se mueven con el cambio de hora. La lectura completa dura unos 12 minutos.

| Días | Franja | Lecturas |
|---|---|---|
| Lunes a viernes | 6:00–15:59 | cada 30 min |
| Lunes a viernes | 16:00–23:59 | cada hora |
| Sábado y domingo | 6:00–15:59 | cada hora |
| Sábado y domingo | 16:00–23:59 | a las 19:07 y a las 22:07 |
| Todos | 0:00–5:59 | ninguna |

Una oferta se da por cerrada tras 3 lecturas seguidas sin verla (`MISSED_RUNS_TO_CLOSE`, `empleo/ingest.py`): entre semana por la mañana, 1,5 h. Si cambias el horario, revisa ese valor y los textos de la web que lo mencionan (`empleo/site.py`, `docs/api.md`).

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
