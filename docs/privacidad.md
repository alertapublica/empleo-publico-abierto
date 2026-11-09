# Datos personales

- La web y el RSS no recogen datos de quien los usa. No hay cuentas ni cookies.
- Los avisos por Telegram guardan solo el identificador del chat y los criterios del aviso (en D1, Cloudflare). `/baja` lo borra todo, y también se borra si la persona bloquea el bot.
- Los avisos por correo guardan la dirección, los criterios y la fecha de alta (en D1, Cloudflare), con doble confirmación: sin confirmar, se borran a las 48 horas. El enlace de baja de cada correo lo borra todo. Los envía el SMTP de Piensa, y el formulario usa Turnstile de Cloudflare contra el envío automatizado.
- De los procesos indefinidos solo se guardan título, fecha y enlace oficial.
- No se copian listas de personas candidatas y se omiten los códigos de candidatura.
- Nunca se automatiza una inscripción.

Funcionamiento de los avisos: [avisos.md](avisos.md).
