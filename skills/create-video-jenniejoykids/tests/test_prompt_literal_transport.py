"""Literal Comfy prompt links, plus an offline installed-frontend regression."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from build_comfy_workflow import build_workflow
from compile_prompts import compile_project


def scene():
    project = json.loads((ROOT / 'examples/zoo-60s.json').read_text(encoding='utf-8'))
    source = compile_project(project)['VIDEO'][0]
    payload = json.loads(source['prompt'].split('\n', 1)[1])
    payload['action'] = source['action'] = (
        'Walk forward while off-screen voiceover is reserved for later editorial. '
        'Keep {rose|pink} wardrobe notation and "gentle" emphasis literal. '
        'Reference https://example.test/zoo/*welcome*/ remains production data.')
    source['prompt'] = 'Expanded visual scene\n' + json.dumps(payload, ensure_ascii=False)
    return source


def native_graph():
    source = scene()
    wrapper, provenance = build_workflow({
        'reference_images': ['family.png'], 'reference_audio': 'alice.wav',
        'guide_audio': 'original.wav', 'dialogue_presentation': 'voiceover',
        'native_speech_conditioning': False}, source)
    return source, wrapper['prompt'], provenance


class PromptLiteralTests(unittest.TestCase):
    def test_exact_literal_string_link_keeps_complete_json_cast_urls_quotes_and_pipes(self):
        source, graph, provenance = native_graph()
        self.assertEqual(['19', 0], graph['6']['inputs']['prompt'])
        self.assertEqual('PrimitiveStringMultiline', graph['19']['class_type'])
        literal = graph['19']['inputs']['value']
        runtime = json.loads(literal.split('\n', 2)[2])
        self.assertEqual(source['characters'], runtime['characters'])
        self.assertEqual(source['image_style_library'], runtime['image_style_library'])
        self.assertEqual(source['action'], runtime['action'])
        self.assertIn('https://example.test/zoo/*welcome*/', literal)
        self.assertIn('{rose|pink}', literal)
        self.assertIn('"gentle"', runtime['action'])
        self.assertNotIn('<Audio 1>', literal)
        self.assertNotIn('dialogue', runtime)
        self.assertEqual('19', provenance['runtime_prompt_node'])
        self.assertEqual('literal_string_link', provenance['runtime_prompt_transport'])
        self.assertEqual(graph, json.loads(json.dumps(graph)))
        self.assertEqual(source, scene())

    def test_installed_real_dynamic_parser_excludes_literal_widget(self):
        """Run the actual installed extension/parser functions in Node, no UI."""
        comfy = Path(os.environ.get('COMFYUI_ROOT', Path.cwd() / 'production-local/ComfyUI'))
        assets = comfy / '.venv/Lib/site-packages/comfyui_frontend_package/static/assets'
        node = shutil.which('node')
        if node is None or not assets.is_dir():
            self.skipTest('Node and installed frontend assets required for offline integration')
        format_files = sorted(assets.glob('formatUtil-*.js'))
        core_files = sorted(assets.glob('core-*.js'))
        objects = comfy.parent / 'installed-object-info.json'
        if not format_files or not core_files or not objects.is_file():
            self.skipTest('Installed frontend parser/extension and schema snapshot unavailable')
        formatter = format_files[0].read_text(encoding='utf-8')
        start = formatter.index('function processDynamicPrompt(')
        end = formatter.index('function isValidUrl(', start)
        parser = formatter[start:end].strip()
        core = core_files[0].read_text(encoding='utf-8')
        extension = core.index('name:`Comfy.DynamicPrompts`')
        start = core.index('nodeCreated(e){', extension)
        brace = core.index('{', start)
        level, end = 1, brace + 1
        while level:
            level += (core[end] == '{') - (core[end] == '}')
            end += 1
        method = 'function' + core[start + len('nodeCreated'):end]
        self.assertIn('e.widgets.filter(e=>e.dynamicPrompts)', method)
        definitions = json.loads(objects.read_text(encoding='utf-8-sig'))
        literal_spec = definitions['PrimitiveStringMultiline']['input']['required']['value'][1]
        dynamic_spec = definitions['MiniMaxH3ReferenceToVideo']['input']['required']['prompt'][1]
        self.assertNotIn('dynamicPrompts', literal_spec)
        self.assertTrue(dynamic_spec['dynamicPrompts'])
        primitive_source = (comfy / 'comfy_extras/nodes_primitive.py').read_text(encoding='utf-8')
        primitive_class = primitive_source.split('class StringMultiline(', 1)[1].split('\nclass ', 1)[0]
        self.assertIn('io.String.Input("value", multiline=True)', primitive_class)
        self.assertIn('return io.NodeOutput(value)', primitive_class)
        _, graph, _ = native_graph()
        literal = graph['19']['inputs']['value']
        program = r'''
const fs = require('node:fs');
const vm = require('node:vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const parser = vm.runInNewContext('(' + input.parser + ')');
const alias = /let r=([A-Za-z_$][\w$]*)\(e.value\)/.exec(input.extension)[1];
const attach = vm.runInNewContext('(' + input.extension + ')', {[alias]: parser});
function widget(spec) {
  const value = {value: input.value};
  if (typeof spec.dynamicPrompts === 'boolean') value.dynamicPrompts = spec.dynamicPrompts;
  return value;
}
const literal = widget(input.literalSpec);
const dynamic = widget(input.dynamicSpec);
attach({widgets: [literal]});
attach({widgets: [dynamic]});
process.stdout.write(JSON.stringify({
  literalHadParser: typeof literal.serializeValue === 'function',
  literalValue: literal.serializeValue ? literal.serializeValue({}, 0) : literal.value,
  dynamicHadParser: typeof dynamic.serializeValue === 'function',
  dynamicValue: dynamic.serializeValue({}, 0)
}));
'''
        result = subprocess.run([node, '-e', program], input=json.dumps({
            'parser': parser, 'extension': method, 'literalSpec': literal_spec,
            'dynamicSpec': dynamic_spec, 'value': literal}), text=True,
            capture_output=True, timeout=15, check=False)
        self.assertEqual(0, result.returncode, result.stderr)
        decoded = json.loads(result.stdout)
        self.assertFalse(decoded['literalHadParser'])
        self.assertEqual(literal, decoded['literalValue'])
        self.assertTrue(decoded['dynamicHadParser'])
        self.assertNotEqual(literal, decoded['dynamicValue'])
        self.assertNotIn('https://example.test/zoo/*welcome*/', decoded['dynamicValue'])
        self.assertEqual(graph['19']['inputs']['value'], decoded['literalValue'])


if __name__ == '__main__':
    unittest.main()
