"""Preregister all isolated exit comparisons before evaluating development data."""
import argparse
import json
from pathlib import Path
from app.ml.research import register, run_experiment, write_json


def run_suite(manifest, protocol_path, output, candidate='auto'):
    protocol=json.loads(Path(protocol_path).read_text())
    if protocol['risk'].get('risk_per_trade_pct',0)<=0:
        raise ValueError('A matched per-trade risk budget is required')
    root=Path(output)
    root.mkdir(parents=True,exist_ok=False)
    variants=('fixed','atr','trailing','time','no-progress')
    # Never pick variants/parameters after looking at another variant's results.
    for variant in variants:
        directory=root/variant
        directory.mkdir()
        configured={**protocol,'candidates':[candidate], 'exit_experiment':{'variant':variant}}
        source=directory/'protocol-input.json'
        write_json(source,configured)
        register(manifest,source,directory)
    reports=[]
    for variant in variants:
        print(f'Evaluating exit policy {variant}; holdout remains untouched',flush=True)
        artifact=run_experiment(root/variant,candidate=candidate)
        data=json.loads(artifact.read_text())
        result=data['result']
        reports.append({'variant':variant,'artifact':str(artifact.resolve()),
            'return':result['total_return_pct'],'stress_return':data['cost_stress']['total_return_pct'],
            'drawdown':result['max_drawdown_pct'],'closed_trades':result['closed_trades'],
            'expectancy':result['expectancy'],'fees':result['total_fees']})
        print(json.dumps(reports[-1]),flush=True)
    write_json(root/'summary.json',{'candidate':candidate,'results':reports,'holdout_consumed':False,
        'limitations':['Development comparisons only; no live activation or profitability claim.',
                      'A maximum holding time already configured in the baseline remains in every variant.']})
    return root/'summary.json'


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',required=True); parser.add_argument('--protocol',required=True)
    parser.add_argument('--output',required=True); parser.add_argument('--candidate',default='auto')
    args=parser.parse_args()
    print(run_suite(args.manifest,args.protocol,args.output,args.candidate))
