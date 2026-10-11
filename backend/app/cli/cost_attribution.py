"""Diagnose a saved development artifact without rerunning or consuming final tests."""
import argparse
import json
from pathlib import Path
from app.ml.cost_attribution import attribution
from app.ml.evaluation import digest


def saved_report(path):
    content=path.read_text(encoding='utf-8')
    artifact=json.loads(content)
    scenarios={name:attribution(artifact[name]) for name in ('result','cost_stress','momentum_baseline')
               if name in artifact}
    if not scenarios:
        scenarios={'result':attribution(artifact)}
    return {'source':str(path.resolve()),'source_sha256':digest(artifact),'scenarios':scenarios,
            'new_strategy_evaluation':False,'holdout_consumed':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('artifact',type=Path)
    parser.add_argument('--output',type=Path)
    options=parser.parse_args()
    content=json.dumps(saved_report(options.artifact),indent=2,allow_nan=False)+'\n'
    if options.output:
        options.output.write_text(content,encoding='utf-8')
    print(content)
