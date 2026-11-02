'use strict';

// Reused in-process conversion from the brand kit; package root is injected by webpack options.
// It leaves ESM syntax for webpack and converts JSX to React.createElement.

const path = require('node:path');
const {createRequire} = require('node:module');
function memberName(node, t) {
  if (t.isJSXIdentifier(node)) {
    return /^[a-z]|-/u.test(node.name)
      ? t.stringLiteral(node.name)
      : t.identifier(node.name);
  }
  if (t.isJSXMemberExpression(node)) {
    return t.memberExpression(memberName(node.object, t), memberName(node.property, t));
  }
  throw new Error(`Unsupported JSX element name: ${node.type}`);
}

function cleanText(value, t) {
  const lines = value.split(/\r\n|\n|\r/u);
  let lastNonEmptyLine = 0;
  lines.forEach((line, index) => {
    if (/[^ \t]/u.test(line)) lastNonEmptyLine = index;
  });
  let result = '';
  lines.forEach((line, index) => {
    let trimmed = line.replace(/\t/gu, ' ');
    if (index !== 0) trimmed = trimmed.replace(/^ +/u, '');
    if (index !== lines.length - 1) trimmed = trimmed.replace(/ +$/u, '');
    if (trimmed) {
      if (index !== lastNonEmptyLine) trimmed += ' ';
      result += trimmed;
    }
  });
  return result ? t.stringLiteral(result) : null;
}

function jsxChildren(children, t) {
  const result = [];
  for (const child of children) {
    if (t.isJSXText(child)) {
      const clean = cleanText(child.value, t);
      if (clean) result.push(clean);
      continue;
    }
    if (t.isJSXExpressionContainer(child)) {
      if (!t.isJSXEmptyExpression(child.expression)) result.push(child.expression);
      continue;
    }
    if (t.isJSXSpreadChild(child)) {
      throw new Error('JSX spread children are not supported');
    }
    result.push(child);
  }
  return result;
}

function jsxProps(attributes, t) {
  return attributes.map((attribute) => {
    if (t.isJSXSpreadAttribute(attribute)) {
      return t.spreadElement(attribute.argument);
    }
    const key = t.stringLiteral(attribute.name.name);
    if (!attribute.value) return t.objectProperty(key, t.booleanLiteral(true));
    if (t.isStringLiteral(attribute.value)) {
      return t.objectProperty(key, attribute.value);
    }
    if (t.isJSXExpressionContainer(attribute.value)) {
      return t.objectProperty(key, attribute.value.expression);
    }
    return t.objectProperty(key, attribute.value);
  });
}

function createElement(name, props, children, t) {
  const args = [name, props.length ? t.objectExpression(props) : t.nullLiteral()];
  args.push(...children);
  return t.callExpression(
    t.memberExpression(t.identifier('React'), t.identifier('createElement')),
    args,
  );
}

function jsxPlugin({types: t}) {
  return {
    name: 'episode-jsx-to-create-element',
    visitor: {
      JSXElement: {
        exit(path) {
          const node = path.node;
          path.replaceWith(
            createElement(
              memberName(node.openingElement.name, t),
              jsxProps(node.openingElement.attributes, t),
              jsxChildren(node.children, t),
              t,
            ),
          );
        },
      },
      JSXFragment: {
        exit(path) {
          const fragment = t.memberExpression(
            t.identifier('React'),
            t.identifier('Fragment'),
          );
          path.replaceWith(
            createElement(fragment, [], jsxChildren(path.node.children, t), t),
          );
        },
      },
    },
  };
}

module.exports = function jsxLoader(source) {
  const {packages} = this.getOptions();
  const babel = createRequire(path.join(packages, 'package.json'))('@babel/core');
  const callback = this.async();
  babel
    .transformAsync(source, {
      filename: this.resourcePath,
      babelrc: false,
      configFile: false,
      sourceMaps: Boolean(this.sourceMap),
      parserOpts: {sourceType: 'unambiguous', plugins: ['jsx']},
      plugins: [jsxPlugin],
      generatorOpts: {retainLines: true},
    })
    .then(
      (result) => callback(null, result.code, result.map || undefined),
      (error) => callback(error),
    );
};
