# Worker de Cloudflare (cron de la ingesta)

El cron de GitHub se salta muchas ejecuciones, así que un worker (`worker/`, cuenta `empleo-publico`) lanza `actualizar.yml` con `workflow_dispatch`. También lanza la lectura nocturna del PAG (`noche.yml` de un repo privado aparte, el del secreto `PAG_REPO`) a las 2:07, 3:07 y 5:07 UTC (`tocaPag()`), dentro del horario que permite su robots.txt (01:00–06:45 GMT), con `si_falta`: la lectura solo se hace si ese día aún no hay. Se despliega solo al fusionar en `main` (`.github/workflows/worker.yml`).

## Horario (hora de Madrid)

El cron se dispara a :07 y a :37 de cada hora (UTC) y `toca()` (`worker/src/index.js`) decide con la hora de Madrid si lanza, de modo que las franjas no se mueven con el cambio de hora. La lectura completa dura unos 12 minutos.

| Días | Franja | Lecturas |
|---|---|---|
| Lunes a viernes | 6:00–18:59 | cada 30 min |
| Lunes a viernes | 19:00–23:59 | a las 20:07 y a las 22:07 |
| Sábado y domingo | 6:00–23:59 | cada 3 horas: 8:07, 11:07, 14:07, 17:07 y 20:07 |
| Todos | 0:00–5:59 | ninguna |

Son 28 lecturas cada día laborable y 5 cada día del fin de semana. El horario sigue a cuándo publican los organismos: en un recuento de novedades por hora de detección (7 días laborables de noviembre de 2026), el 91 % llegó entre las 6:00 y las 16:00, el 9 % de 16:00 a 19:00 y nada después de las 20:00; en fin de semana, casi nada que no fuera el alta de una fuente nueva. Conviene repetir el recuento con más datos.

Una oferta se da por cerrada tras 3 lecturas seguidas sin verla (`MISSED_RUNS_TO_CLOSE`, `empleo/ingest.py`): 1,5 h si las tres caen en la franja de cada 30 minutos; si cruzan la noche o el fin de semana, bastante más: de un día laborable a otro, unas 11,5 h (última vista a las 18:37, cerrada a las 6:07), y en fin de semana hasta 18 h (vista el sábado a las 14:07, cerrada el domingo a las 8:07; 19 h el día que se retrasa el reloj). Las ofertas que vencen se cierran por la fecha del plazo, no por esto. Si cambias el horario, revisa ese valor y el horario que publica la web (`SCHEDULE` y `SCHEDULE_SUMMARY`, `empleo/site.py`).

## Secretos

- **Del repo:** `CLOUDFLARE_API_TOKEN` (token acotado de despliegue), `CLOUDFLARE_ACCOUNT_ID` y `AVISOS_CLAVE` (ver [avisos](avisos.md)).
- **Del worker:** `GITHUB_TOKEN`, un token de grano fino solo para este repo y el del PAG con «Actions: read and write», y `PAG_REPO` (`dueño/nombre`; sin él no se lanza la lectura del PAG).

  ```bash
  cd worker && wrangler secret put GITHUB_TOKEN && wrangler secret put PAG_REPO
  ```

## Tests

```bash
cd worker && node --test test/index.test.mjs
```
