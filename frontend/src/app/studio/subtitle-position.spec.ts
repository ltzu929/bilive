import { subtitlePosition } from './subtitle-position';

describe('ASS subtitle position', () => {
  it('maps all nine positions to the same preview grid', () => {
    for (let row = 0; row < 3; row++) for (let col = 0; col < 3; col++) {
      expect(subtitlePosition(row * 3 + col + 1)).toEqual({
        horizontal: ['flex-start', 'center', 'flex-end'][col],
        vertical: ['flex-end', 'center', 'flex-start'][row],
      });
    }
  });
});
