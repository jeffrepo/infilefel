#!/usr/bin/env python3
"""Validate this module's XML data against the target Odoo import schema.

Uses lxml without importing Odoo or requiring a running database.
"""

import argparse
import ast
from pathlib import Path

from lxml import etree


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--schema', type=Path, required=True,
        help='Path to odoo/import_xml.rng in the target Odoo source checkout.',
    )
    args = parser.parse_args()
    module = Path(__file__).resolve().parents[1]
    manifest = ast.literal_eval((module / '__manifest__.py').read_text(encoding='utf-8'))
    schema = etree.RelaxNG(etree.parse(str(args.schema)))
    failed = False
    checked = 0
    for name in dict.fromkeys(manifest.get('data', []) + manifest.get('demo', [])):
        if not name.endswith('.xml'):
            continue
        checked += 1
        try:
            schema.assertValid(etree.parse(str(module / name)))
        except (etree.DocumentInvalid, etree.XMLSyntaxError, OSError) as error:
            print(f'FAIL {name}: {error}')
            failed = True
        else:
            print(f'PASS {name}')
    print(f'{checked} XML files checked.')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
