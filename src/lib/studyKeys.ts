export type KeyCommand = 'toggle' | 'prev' | 'next' | 'replay' | 'repeat' | 'autoPause' | 'slower' | 'faster' | 'eng' | 'syncEarlier' | 'syncLater' | 'help' | 'close';

export type KeyInput = { key: string; ctrlKey: boolean; metaKey: boolean; altKey: boolean };

// 공부 화면의 단축키 표(Language Reactor와 asbplayer 관례). 입력칸에 있거나 Ctrl/Meta/Alt가 눌려 있으면 아무것도 하지 않는다.
export function keyCommand(e: KeyInput, inEditable: boolean): KeyCommand | null {
  if (inEditable || e.ctrlKey || e.metaKey || e.altKey) return null;
  switch (e.key) {
    case ' ':
      return 'toggle';
    case 'ArrowLeft':
    case 'a':
    case 'A':
      return 'prev';
    case 'ArrowRight':
    case 'd':
    case 'D':
      return 'next';
    case 'ArrowDown':
    case 's':
    case 'S':
      return 'replay';
    case 'r':
    case 'R':
      return 'repeat';
    case 'q':
    case 'Q':
      return 'autoPause';
    case '[':
      return 'slower';
    case ']':
      return 'faster';
    case 'c':
    case 'C':
      return 'eng';
    case ',':
      return 'syncEarlier';
    case '.':
      return 'syncLater';
    case '?':
      return 'help';
    case 'Escape':
      return 'close';
    default:
      return null;
  }
}

export const SHORTCUTS: readonly { keys: string; label: string }[] = [
  { keys: 'Space', label: '재생 / 일시정지' },
  { keys: '← A', label: '이전 줄' },
  { keys: '→ D', label: '다음 줄' },
  { keys: '↓ S', label: '이 줄 다시' },
  { keys: 'R', label: '반복: 끔, 3번, 무한' },
  { keys: 'Q', label: '줄마다 멈춤 켜기 / 끄기' },
  { keys: '[  ]', label: '속도 내리기 / 올리기' },
  { keys: 'C', label: '영어 자막: 보임, 흐림, 숨김' },
  { keys: ', .', label: '자막 싱크 -0.1초 / +0.1초' },
  { keys: '?', label: '단축키 도움말' },
  { keys: 'Esc', label: '닫기' },
];
