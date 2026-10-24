import { describe, expect, test } from 'bun:test';
import { clipKey, clipThumbnail, firstUrl, linkLabel, mutedEmbedUrl, parseSharedClip, parseShareAck, withoutUrl } from './share';

const CLIP = { video_id: 'dramaVideo01', start: 10, end: 14, text: 'And all of a sudden the lights went out.', title: 'Drama Night', channel: 'Drama Channel' };

describe('parseSharedClip', () => {
  test('reads the clip the server sends', () => {
    expect(parseSharedClip({ type: 'shared_clip', clip: CLIP })).toEqual(CLIP);
  });

  test('rejects a bad video id, missing times or an empty line', () => {
    expect(parseSharedClip({ clip: { ...CLIP, video_id: 'a b' } })).toBeNull();
    expect(parseSharedClip({ clip: { ...CLIP, start: 'x' } })).toBeNull();
    expect(parseSharedClip({ clip: { ...CLIP, start: -1 } })).toBeNull();
    expect(parseSharedClip({ clip: { ...CLIP, text: '  ' } })).toBeNull();
    expect(parseSharedClip({})).toBeNull();
    expect(parseSharedClip(null)).toBeNull();
  });

  test('end never comes before start and missing labels become empty strings', () => {
    const clip = parseSharedClip({ clip: { video_id: 'dramaVideo01', start: 20, end: 5, text: 'hi there' } });
    expect(clip).toEqual({ video_id: 'dramaVideo01', start: 20, end: 20, text: 'hi there', title: '', channel: '' });
  });
});

describe('parseShareAck', () => {
  test('keeps only the typed fields', () => {
    expect(parseShareAck({ type: 'share_ack', id: '3', ok: true, url: 'https://a.example', title: 'A', opened: true, extra: 1 })).toEqual({
      id: '3',
      ok: true,
      url: 'https://a.example',
      title: 'A',
      opened: true,
    });
    expect(parseShareAck({ type: 'share_ack', id: '4', ok: false })).toEqual({ id: '4', ok: false });
  });

  test('ignores other messages and acks without an id', () => {
    expect(parseShareAck({ type: 'paused' })).toBeNull();
    expect(parseShareAck({ type: 'share_ack', ok: true })).toBeNull();
    expect(parseShareAck(undefined)).toBeNull();
  });
});

describe('links in sent text', () => {
  test('firstUrl finds the first link and trims trailing punctuation', () => {
    expect(firstUrl('look https://youtu.be/abc12345678, wow')).toBe('https://youtu.be/abc12345678');
    expect(firstUrl('(www.example.com/a?b=1).')).toBe('https://www.example.com/a?b=1');
    expect(firstUrl('youtube.com/watch?v=abc12345678!')).toBe('https://youtube.com/watch?v=abc12345678');
    expect(firstUrl('just a plain message')).toBeNull();
  });

  test('withoutUrl leaves what the learner wrote around the link', () => {
    expect(withoutUrl('check this https://bread.example/tips it is great')).toBe('check this it is great');
    expect(withoutUrl('https://bread.example/tips')).toBe('');
  });

  test('linkLabel prefers the title and falls back to host and path', () => {
    expect(linkLabel('https://www.bread.example/tips/1', 'Best tips')).toBe('Best tips');
    expect(linkLabel('https://www.bread.example/tips/1')).toBe('bread.example/tips/1');
    expect(linkLabel('https://www.bread.example/')).toBe('bread.example');
  });
});

describe('clip helpers', () => {
  test('key, thumbnail and muted embed use the clip time window', () => {
    expect(clipKey(CLIP)).toBe('dramaVideo01:10');
    expect(clipThumbnail('dramaVideo01')).toBe('https://i.ytimg.com/vi/dramaVideo01/mqdefault.jpg');
    const url = new URL(mutedEmbedUrl(CLIP));
    expect(url.hostname).toBe('www.youtube-nocookie.com');
    expect(url.pathname).toBe('/embed/dramaVideo01');
    expect(url.searchParams.get('mute')).toBe('1');
    expect(url.searchParams.get('start')).toBe('10');
    expect(url.searchParams.get('end')).toBe('15');
  });
});
