/* Decoder work is isolated from native playback and the rendering thread. */
let decoder;
self.onmessage = async ({data}) => {
  const {id, type, bytes} = data;
  try {
    if (type === 'init') {
      if (decoder) throw new Error('Decoder already initialized');
      importScripts('/static/vendor/mpg123/mpg123-decoder.min.js?v=1.0.3');
      decoder = new self['mpg123-decoder'].MPEGDecoder({enableGapless: false});
      await decoder.ready;
      self.postMessage({id, ready: true});
    } else if (type === 'decode') {
      if (!decoder || !(bytes instanceof Uint8Array) || bytes.length > 8192) throw new Error('Invalid decoder input');
      const {channelData, samplesDecoded, sampleRate} = decoder.decode(bytes);
      if (samplesDecoded && (channelData.length > 2 || sampleRate < 8000 || sampleRate > 48000 || samplesDecoded > sampleRate * 10))
        throw new Error('Unsupported decoded audio');
      self.postMessage({id, channelData, samplesDecoded, sampleRate}, [...new Set(channelData.map(channel => channel.buffer))]);
    } else throw new Error('Unknown decoder operation');
  } catch (error) {self.postMessage({id, error: error.name + ': ' + error.message});}
};
