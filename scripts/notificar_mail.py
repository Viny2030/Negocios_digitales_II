"""
Manda por mail el resultado de un levantamiento de canales (lo llaman los workflows al final).
Usa solo la biblioteca estándar (smtplib), sin actions de terceros que reciban los secrets.

    python -m scripts.notificar_mail

Variables de entorno:
  SMTP_USERNAME, SMTP_PASSWORD, MAIL_TO   cuenta que envía, su contraseña de aplicación y destino
  SMTP_HOST (default smtp.gmail.com), SMTP_PORT (default 465, SSL)
  ESTADO   resultado del job: success | failure | cancelled
  MODO     principal | respaldo
  FOTO     tomada | ya_estaba | vacío (no se llegó a tomar)
  RUN_URL  link a la corrida en GitHub
  RESUMEN_PATH  archivo Markdown con el detalle (opcional)

Sin SMTP_USERNAME / SMTP_PASSWORD / MAIL_TO avisa y sale con 0: el mail es opcional. Si el envío
falla sale con 1, así el job queda en rojo y GitHub manda además su propio aviso de falla.
"""
import os
import smtplib
import ssl
import sys
from email.message import EmailMessage
from pathlib import Path

PREFIX = "[Channel Analytics]"


def build_subject(estado: str, modo: str, foto: str) -> str:
    quien = "Levantamiento de respaldo" if modo == "respaldo" else "Levantamiento diario"
    if estado == "success" and foto == "ya_estaba":
        resultado = "la foto de hoy ya estaba tomada"
    elif estado == "success":
        resultado = "OK, foto del día tomada"
    elif estado == "cancelled":
        resultado = "CANCELADO"
    else:
        resultado = "FALLÓ, revisar"
    return f"{PREFIX} {quien}: {resultado}"


def build_body(estado: str, run_url: str, resumen: str) -> str:
    parts = []
    if estado != "success":
        parts.append(
            "La corrida no terminó bien. Si fue la principal, el respaldo de las 21:00 UTC lo "
            "reintenta; si fue el respaldo, hoy queda sin foto salvo que se corra a mano "
            "(Actions > Levantamiento diario de canales > Run workflow)."
        )
    parts.append(resumen.strip() or "Sin detalle: la corrida falló antes de tomar la foto.")
    if run_url:
        parts.append(f"Detalle de la corrida: {run_url}")
    return "\n\n".join(parts) + "\n"


def main() -> int:
    user = os.environ.get("SMTP_USERNAME", "")
    password = os.environ.get("SMTP_PASSWORD", "")
    to = os.environ.get("MAIL_TO", "")
    if not (user and password and to):
        print("::warning::Mail no configurado (faltan SMTP_USERNAME, SMTP_PASSWORD o MAIL_TO): no se envía.")
        return 0

    estado = os.environ.get("ESTADO", "failure")
    resumen_path = os.environ.get("RESUMEN_PATH", "")
    resumen = Path(resumen_path).read_text(encoding="utf-8") if resumen_path and Path(resumen_path).exists() else ""

    message = EmailMessage()
    message["Subject"] = build_subject(estado, os.environ.get("MODO", "principal"), os.environ.get("FOTO", ""))
    message["From"] = user
    message["To"] = to
    message.set_content(build_body(estado, os.environ.get("RUN_URL", ""), resumen))

    host = os.environ.get("SMTP_HOST") or "smtp.gmail.com"
    port = int(os.environ.get("SMTP_PORT") or 465)
    try:
        with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=30) as smtp:
            smtp.login(user, password)
            smtp.send_message(message)
    except (smtplib.SMTPException, OSError) as exc:
        print(f"::error::No se pudo enviar el mail: {type(exc).__name__}: {exc}")
        return 1
    print(f"Mail enviado: {message['Subject']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
