#!/usr/bin/env python3
"""
scripts/poblar_bd.py — Sincronización inicial con Mercado Público.
Usa el ticket del .env (TICKET_MERCADO_PUBLICO) o el primer usuario activo.

Uso:
  python scripts/poblar_bd.py                    # hoy, licitaciones + OC
  python scripts/poblar_bd.py --dias 7            # últimos 7 días
  python scripts/poblar_bd.py --tipo licitacion   # solo licitaciones
  python scripts/poblar_bd.py --max 5000          # hasta 5000 registros por tipo
  python scripts/poblar_bd.py --dry-run           # sin escribir
"""
import sys, os, argparse, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dotenv import load_dotenv; load_dotenv()
logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s")

from datetime import datetime, timedelta
from app.database import init_db, get_db
from app.models import LicitacionSnapshot, UserTicket
from app.api_client import MercadoPublicoClient, QuotaExhaustedException
from app.normalizer import normalizar_entidad

G="\033[92m"; Y="\033[93m"; C="\033[96m"; R="\033[91m"; B="\033[1m"; NC="\033[0m"
LIMITES = {"licitacion": 20_000, "orden_compra": 5_000}

def _obtener_ticket() -> str:
    ticket = os.environ.get("TICKET_MERCADO_PUBLICO", "").strip()
    if ticket: return ticket
    # Buscar ticket del primer usuario activo
    from app.crypto import descifrar_ticket
    with get_db() as db:
        ut = db.query(UserTicket).filter_by(activo=True).first()
        if ut:
            return descifrar_ticket(ut.ticket_cifrado)
    raise RuntimeError("Sin ticket disponible. Define TICKET_MERCADO_PUBLICO en .env o crea un usuario con ticket.")

def run(dias, tipos, max_reg, dry_run):
    print(f"\n{B}Poblar BD — Mercado Público{NC}")
    print(f"  Período: {dias} día(s) | Tipos: {', '.join(tipos)} | {'DRY RUN' if dry_run else 'ESCRITURA'}\n")
    init_db()
    ticket = _obtener_ticket()
    client = MercadoPublicoClient(ticket=ticket)
    fecha_d = datetime.now() - timedelta(days=dias)
    fecha_s = client.to_api_date(fecha_d)
    totales = {"insertados": 0, "actualizados": 0, "omitidos": 0}

    for tipo in tipos:
        if tipo == "compra_agil":
            print(f"{Y}── COMPRA_AGIL omitida (API no soporta tipo=CO){NC}\n"); continue
        limite = min(max_reg, LIMITES.get(tipo, 5_000)) if max_reg > 0 else LIMITES.get(tipo, 5_000)
        print(f"{C}── {tipo.upper()} (hasta {limite:,}) ──{NC}")
        iterador = client.iter_licitaciones(fecha_desde=fecha_s) if tipo == "licitacion" else client.iter_ordenes_compra(fecha_desde=fecha_s)
        lote, seen, n, detenido = [], set(), 0, False
        try:
            for raw in iterador:
                entidad = normalizar_entidad(raw, tipo)
                if not entidad: continue
                codigo = entidad.get("codigo", "")
                if not codigo or codigo in seen: totales["omitidos"]+=1; continue
                seen.add(codigo); lote.append(entidad); n+=1
                if n % 100 == 0: print(f"\r  {'█'*min(40,n//100)}{'░'*max(0,40-n//100)} {n:,}…", end="", flush=True)
                if len(lote) >= 500 and not dry_run: _guardar(lote, tipo, totales); lote=[]
                if n >= limite: print(f"\n  {Y}Límite {limite:,} alcanzado.{NC}"); detenido=True; break
        except QuotaExhaustedException: print(f"\n  {R}Cuota agotada.{NC}"); break
        except KeyboardInterrupt: print(f"\n  {Y}Interrumpido.{NC}"); break
        if lote:
            if dry_run: totales["insertados"]+=len(lote)
            else: _guardar(lote, tipo, totales)
        print(f"\n  {'✅' if not detenido else '⚠️ '} {tipo}: {n:,} procesados\n")

    with get_db() as db:
        total_bd = db.query(LicitacionSnapshot).count()
    print(f"{B}Insertados:{NC} {totales['insertados']:,} | {B}Actualizados:{NC} {totales['actualizados']:,} | {B}Total BD:{NC} {total_bd:,}")
    if not dry_run and total_bd > 0:
        print(f"\n  {G}→ python main.py --once   para evaluar reglas{NC}\n")

def _guardar(lote, tipo, totales):
    from datetime import datetime as dt
    with get_db() as db:
        codigos = [e["codigo"] for e in lote if e.get("codigo")]
        existentes = {r.codigo for r in db.query(LicitacionSnapshot.codigo).filter(LicitacionSnapshot.codigo.in_(codigos)).all()}
        for entidad in lote:
            codigo = entidad.get("codigo","")
            if not codigo: continue
            fp = None
            for field in ("fecha_publicacion","fecha_cierre"):
                if entidad.get(field):
                    try: fp = dt.strptime(entidad[field], "%Y-%m-%d"); break
                    except: pass
            if codigo in existentes:
                db.query(LicitacionSnapshot).filter_by(codigo=codigo).update({"datos":entidad,"region":entidad.get("region"),"monto_clp":entidad.get("monto_clp"),"estado":entidad.get("estado"),"fecha_publicacion":fp})
                totales["actualizados"]+=1
            else:
                db.add(LicitacionSnapshot(codigo=codigo, tipo=tipo, datos=entidad, region=entidad.get("region"), monto_clp=entidad.get("monto_clp"), estado=entidad.get("estado"), fecha_publicacion=fp))
                existentes.add(codigo); totales["insertados"]+=1

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--dias",    type=int, default=1)
    p.add_argument("--tipo",    nargs="+", choices=["licitacion","orden_compra"], default=["licitacion","orden_compra"])
    p.add_argument("--max",     type=int, default=0)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    run(args.dias, args.tipo, args.max, args.dry_run)
