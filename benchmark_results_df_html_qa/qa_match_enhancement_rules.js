(function (global) {
  function dedupeCandidates(candidates) {
    const seen = new Set();
    const out = [];
    candidates.forEach((candidate) => {
      const text = String(candidate && candidate.text ? candidate.text : '').trim();
      if (!text) return;
      const key = text.toLowerCase();
      if (seen.has(key)) return;
      seen.add(key);
      out.push({ text, rule: candidate.rule || 'fallback' });
    });
    return out;
  }

  function normalizeSpaces(text) {
    return String(text || '').replace(/\s+/g, ' ').trim();
  }

  function normalizeAlphaNum(text) {
    return normalizeSpaces(text).toLowerCase().replace(/[^a-z0-9]+/g, '');
  }

  function isNarrativeAnswer(text) {
    const s = normalizeSpaces(text).toLowerCase();
    if (!s) return false;
    return s.startsWith('the user ') || s.startsWith('based on ') || s.split(' ').length > 18;
  }

  function isWrongPrediction(row) {
    const m = row && row.metrics ? row.metrics : {};
    if (m.overall_correct === true) return false;
    if (m.primary_value_match === true) return false;
    if (m.normalized_exact === true) return false;
    if (m.number_match === true && m.unit_match !== false) return false;
    return true;
  }

  function toNumberText(value) {
    if (!Number.isFinite(value)) return '';
    let s = String(value);
    if (s.includes('e') || s.includes('E')) s = value.toFixed(12);
    s = s.replace(/0+$/, '').replace(/\.$/, '');
    return s;
  }

  function numericVariants(text) {
    const variants = [];
    const push = (value, rule) => variants.push({ text: value, rule });
    const compact = String(text || '').replace(/[,\s]/g, '');
    const stripped = compact.replace(/^[\$£€]/, '').replace(/%$/, '');
    const numberRegex = /^[+-]?(?:\d+(?:\.\d+)?|\.\d+)$/;
    if (!numberRegex.test(stripped)) return variants;

    const parsed = Number(stripped);
    if (!Number.isFinite(parsed)) return variants;

    const originalDecimals = (() => {
      const match = stripped.match(/\.(\d+)/);
      return match ? match[1].length : 0;
    })();

    const canonical = toNumberText(parsed);
    if (canonical) push(canonical, 'numeric-canonical');

    if (canonical.startsWith('.')) push(`0${canonical}`, 'numeric-leading-zero-add');

    if (originalDecimals > 0) {
      const fixed = parsed.toFixed(originalDecimals);
      push(fixed, 'numeric-fixed-decimals');
    }

    push(stripped, 'numeric-stripped');
    push(`$${stripped}`, 'currency-prefixed');

    return variants;
  }

  function booleanVariants(text) {
    const s = normalizeSpaces(text).toLowerCase();
    if (!s) return [];

    if (['yes', 'y', 'true', '1'].includes(s)) {
      return [
        { text: 'Yes', rule: 'boolean-yes' },
        { text: 'yes', rule: 'boolean-yes' },
        { text: 'YES', rule: 'boolean-yes' },
        { text: 'true', rule: 'boolean-yes' },
        { text: 'True', rule: 'boolean-yes' },
        { text: '1', rule: 'boolean-yes' },
      ];
    }
    if (['no', 'n', 'false', '0'].includes(s)) {
      return [
        { text: 'No', rule: 'boolean-no' },
        { text: 'no', rule: 'boolean-no' },
        { text: 'NO', rule: 'boolean-no' },
        { text: 'false', rule: 'boolean-no' },
        { text: 'False', rule: 'boolean-no' },
        { text: '0', rule: 'boolean-no' },
      ];
    }
    return [];
  }

  function dateVariants(text) {
    const s = normalizeSpaces(text);
    const match = s.match(/^(\d{1,2})\/(\d{1,2})\/(\d{2}|\d{4})$/);
    if (!match) return [];

    const mm = match[1].padStart(2, '0');
    const dd = match[2].padStart(2, '0');
    const yy = match[3];

    if (yy.length === 2) {
      return [
        { text: `${mm}/${dd}/${yy}`, rule: 'date-2digit-year' },
        { text: `${mm}/${dd}/20${yy}`, rule: 'date-4digit-year' },
      ];
    }
    return [
      { text: `${mm}/${dd}/${yy}`, rule: 'date-4digit-year' },
      { text: `${mm}/${dd}/${yy.slice(2)}`, rule: 'date-2digit-year' },
    ];
  }

  function duplicateTextVariants(text) {
    const s = normalizeSpaces(text);
    if (!s || s.length < 12) return [];

    const variants = [];
    const compact = normalizeAlphaNum(s);
    if (!compact || compact.length < 10 || compact.length % 2 !== 0) return variants;

    const half = compact.length / 2;
    if (compact.slice(0, half) !== compact.slice(half)) return variants;

    const rawHalf = Math.floor(s.length / 2);
    variants.push({ text: s.slice(0, rawHalf).replace(/[\s.,;:-]+$/, ''), rule: 'duplicate-collapse-half' });
    return variants;
  }

  function entityPhraseVariants(text) {
    const s = String(text || '');
    if (!s) return [];

    const variants = [];
    const pattern = /\b([A-Z][A-Za-z&'\-]+(?:\s+[A-Z][A-Za-z&'\-.,]*){1,10}\s+(?:Inc\.?|Corporation|Corp\.?|Company|Co\.?|LLC|Ltd\.?|Adviser,\s*Inc\.?))\b/g;
    const matches = [...s.matchAll(pattern)];
    if (!matches.length) return variants;

    matches.forEach((m, idx) => {
      const phrase = normalizeSpaces(m[1]);
      if (!phrase) return;
      variants.push({ text: phrase, rule: idx === 0 ? 'entity-phrase-first' : 'entity-phrase' });
    });
    return variants;
  }

  function buildCandidates(prediction) {
    const p = normalizeSpaces(prediction);
    if (!p || isNarrativeAnswer(p)) return [];

    const candidates = [{ text: p, rule: 'exact' }];

    if (p.startsWith('$')) candidates.push({ text: p.slice(1), rule: 'currency-strip' });
    if (p.endsWith('%')) candidates.push({ text: p.slice(0, -1), rule: 'percent-strip' });

    candidates.push(...numericVariants(p));
    candidates.push(...booleanVariants(p));
    candidates.push(...dateVariants(p));
    candidates.push(...duplicateTextVariants(p));
    candidates.push(...entityPhraseVariants(p));

    return dedupeCandidates(candidates);
  }

  global.QaMatchEnhancement = {
    buildCandidates,
    isWrongPrediction,
    isNarrativeAnswer,
  };
})(window);
