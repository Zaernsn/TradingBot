"""Offline evaluation and read-only forward reporting. Never places orders."""
import argparse
import json
from pathlib import Path

from app.ml.research import register, run_experiment, freeze, write_json, RESEARCH_CANDIDATES


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command',required=True)
    init = commands.add_parser('register')
    init.add_argument('--manifest',required=True); init.add_argument('--protocol',required=True); init.add_argument('--output',required=True)
    run = commands.add_parser('run')
    run.add_argument('directory'); run.add_argument('--stage',choices=['development','holdout'],default='development')
    run.add_argument('--candidate',choices=sorted(RESEARCH_CANDIDATES),default='signal-v2')
    lock = commands.add_parser('freeze')
    lock.add_argument('directory'); lock.add_argument('--candidate',required=True)
    forward = commands.add_parser('forward')
    forward.add_argument('--portfolio-id',type=int,required=True); forward.add_argument('--output',required=True)
    assess = commands.add_parser('assess')
    assess.add_argument('--historical',required=True); assess.add_argument('--forward',required=True); assess.add_argument('--output',required=True)
    args = parser.parse_args()
    try:
        if args.command=='register':
            register(args.manifest,args.protocol,args.output); print(f'Registered: {args.output}')
        elif args.command=='run': print(run_experiment(args.directory,args.stage,args.candidate))
        elif args.command=='freeze': freeze(args.directory,args.candidate); print('Candidate frozen; holdout can be consumed once')
        elif args.command=='forward':
            from app.db.session import SessionLocal
            from app.services.research_service import forward_report
            with SessionLocal() as db: write_json(args.output,forward_report(db,args.portfolio_id))
        else:
            from app.ml.evaluation import promotion_report
            historical=json.loads(Path(args.historical).read_text(encoding='utf-8'))
            forward=json.loads(Path(args.forward).read_text(encoding='utf-8'))
            report=promotion_report(historical.get('result',historical),forward)
            write_json(args.output,report); print(report['decision'])
    except (ValueError,KeyError,FileNotFoundError,FileExistsError) as exc:
        parser.exit(2,f'Research stopped: {exc}\n')


if __name__=='__main__': main()
