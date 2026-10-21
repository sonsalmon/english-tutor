// 학습자 전사 정리. 서버 transcript_clean.clean_learner_text와 같은 규칙이고 두 시험이 같은 입력표를 쓴다.
// Gemini 입력 전사가 짧은 추임새("음")를 한자("嗯")로 내보낼 때 자막에 그대로 보이지 않게 한다.

const CJK_ONE = /[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]/;
const CJK_RUNS = /[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+/g;
const KEEP = /[A-Za-z0-9\u00c0-\u024f\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]/;
export const SHORT_LIMIT = 12;

export function cleanLearnerText(text: string): string {
  if (!text || !CJK_ONE.test(text)) return text;
  if (!KEEP.test(text)) return text.replace(/\s+/g, '').length <= SHORT_LIMIT ? '(mm)' : '(unclear)';
  return text.replace(CJK_RUNS, ' ').split(/\s+/).filter(Boolean).join(' ');
}
