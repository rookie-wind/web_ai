#!/usr/bin/env python3
"""生成测试报告 JSON"""
import unittest
import json
import sys
import os
import io
import re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_protocol_converter as tpc

loader = unittest.TestLoader()

# Explicitly load all TestCase classes from the module using dir()
suite = unittest.TestSuite()
test_class_names = []
for name in dir(tpc):
    obj = getattr(tpc, name, None)
    if (isinstance(obj, type) and issubclass(obj, unittest.TestCase)
            and obj is not unittest.TestCase):
        suite.addTests(loader.loadTestsFromTestCase(obj))
        test_class_names.append(name)

# Use verbose runner to capture per-test results
stream = io.StringIO()
runner = unittest.TextTestRunner(stream=stream, verbosity=2)
result = runner.run(suite)

# Parse verbose output (handles both single-line and multi-line formats)
test_classes = {}
lines = stream.getvalue().split('\n')
i = 0
while i < len(lines):
    line = lines[i]
    # Multi-line format: "test_name (class)\n docstring ... ok"
    m = re.match(r'^(.+?) \((.+?)\)$', line)
    if m and i + 1 < len(lines):
        full_class = m.group(2)
        next_line = lines[i + 1].strip()
        status_m = re.search(r'\.\.\. (\w+)', next_line)
        if status_m:
            status = status_m.group(1)
            class_name = full_class.split('.')[-1] if '.' in full_class else full_class
            if class_name not in test_classes:
                test_classes[class_name] = {'total': 0, 'passed': 0, 'skipped': 0, 'failed': 0}
            test_classes[class_name]['total'] += 1
            if status == 'ok':
                test_classes[class_name]['passed'] += 1
            elif status == 'skipped':
                test_classes[class_name]['skipped'] += 1
            else:
                test_classes[class_name]['failed'] += 1
            i += 2
            continue
    # Single-line format: "test_name (class) ... ok"
    m = re.match(r'^(.+?) \((.+?)\) \.\.\. (\w+)', line)
    if m:
        full_class = m.group(2)
        status = m.group(3)
        class_name = full_class.split('.')[-1] if '.' in full_class else full_class
        if class_name not in test_classes:
            test_classes[class_name] = {'total': 0, 'passed': 0, 'skipped': 0, 'failed': 0}
        test_classes[class_name]['total'] += 1
        if status == 'ok':
            test_classes[class_name]['passed'] += 1
        elif status == 'skipped':
            test_classes[class_name]['skipped'] += 1
        else:
            test_classes[class_name]['failed'] += 1
    i += 1

report = {
    'testTime': '2026-08-20T00:00:00Z',
    'total': result.testsRun,
    'passed': result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped),
    'failed': len(result.failures),
    'errors': len(result.errors),
    'skipped': len(result.skipped),
    'status': 'PASSED' if result.wasSuccessful() else 'FAILED',
    'testClasses': test_classes
}

output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'test_report.json')
with open(output_path, 'w', encoding='utf-8') as f:
    json.dump(report, f, indent=2, ensure_ascii=False)

print(json.dumps(report, indent=2, ensure_ascii=False))
