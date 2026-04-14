#!/usr/bin/env node

const fs = require('fs');
const path = require('path');
const https = require('https');
const { Worker } = require('worker_threads');
const http = require('http');

// ================== CONFIG ==================
const CONFIG = {
  M3U_LIST_FILE: 'M3U_list.txt',
  LIVE_M3U: 'live_schedule_Node.m3u',
  CACHE_FILE: '.m3u_cache.json',
  CACHE_EXPIRY: 3600,
  VALIDATION_CONCURRENT: 50,
  VALIDATION_TIMEOUT: 3000,
  M3U_FETCH_WORKERS: 40,
  USER_AGENT: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
};

const SKIP_VALIDATION = process.argv.includes('--skip-validation');

// ================== API URLs ==================
const FOOTONSAT_URLS = [
  'https://raw.githubusercontent.com/fairbird/footonsat-api/refs/heads/main/premierleague.json',
  'https://raw.githubusercontent.com/fairbird/footonsat-api/refs/heads/main/seriea.json',
  'https://raw.githubusercontent.com/fairbird/footonsat-api/refs/heads/main/laliga.json',
  'https://raw.githubusercontent.com/fairbird/footonsat-api/refs/heads/main/bundesliga.json',
  'https://raw.githubusercontent.com/fairbird/footonsat-api/refs/heads/main/ligue1.json',
  'https://raw.githubusercontent.com/fairbird/footonsat-api/refs/heads/main/championsleague.json',
  'https://raw.githubusercontent.com/fairbird/footonsat-api/refs/heads/main/europaleague.json',
  'https://raw.githubusercontent.com/fairbird/footonsat-api/refs/heads/main/ConferenceLeague.json',
];

const LOVE4VN_URL = 'https://raw.githubusercontent.com/Love4vn/Live-Schedue/refs/heads/1/schedule.json';

// ================== CONSTANTS ==================
const LEAGUE_MAPPING = {
  'english premier league': 'Premier League',
  'serie a': 'Serie A',
  'la liga': 'La Liga',
  'bundesliga': 'Bundesliga',
  'ligue 1': 'Ligue 1',
  'uefa champions league': 'UEFA Champions League',
  'uefa europa league': 'UEFA Europa League',
  'uefa conference league': 'UEFA Europa Conference League',
};

const ALLOWED_LEAGUES = new Set(Object.values(LEAGUE_MAPPING));

const PREMIER_LEAGUE_TEAMS = new Set([
  'arsenal', 'aston villa', 'bournemouth', 'brentford', 'brighton', 'chelsea',
  'crystal palace', 'everton', 'fulham', 'leeds united', 'liverpool', 'manchester city',
  'manchester united', 'newcastle', 'nottingham forest', 'sunderland', 'tottenham hotspur',
  'west ham united', 'wolverhampton'
]);

const ALLOWED_TEAMS = {
  'Premier League': PREMIER_LEAGUE_TEAMS,
  'Serie A': new Set(['inter milan', 'ac milan', 'napoli', 'juventus', 'roma', 'atalanta', 'lazio']),
  'La Liga': new Set(['barcelona', 'real madrid', 'atletico madrid']),
  'Bundesliga': new Set(['bayern munich', 'borussia dortmund', 'bayer leverkusen']),
  'Ligue 1': new Set(['psg', 'paris saint-germain', 'olympique marseille', 'marseille']),
};

const COUNTRY_CODES = new Set([
  'uk', 'us', 'fr', 'de', 'it', 'es', 'pt', 'nl', 'be', 'ch', 'at',
  'se', 'no', 'dk', 'fi', 'pl', 'cz', 'hu', 'ro', 'bg', 'gr', 'tr',
  'il', 'au', 'ca', 'nz', 'ie', 'gb', 'en', 'vn', 'kr', 'jp', 'cn',
  'br', 'ar', 'mx', 'in', 'za', 'ru', 'ua', 'rs', 'hr', 'si', 'sk', 'am'
]);

const LEAGUE_GROUP_NAME = {
  'Premier League': '⚽️🏴󠁧󠁢󠁥󠁮󠁧󠁿|Live Premier League',
  'Serie A': '⚽️🇮🇹|Live Serie A',
  'Bundesliga': '⚽️🇩🇪|Live Bundesliga',
  'La Liga': '⚽️🇪🇦|Live La Liga',
  'Ligue 1': '⚽️🇨🇵|Live Ligue 1',
  'UEFA Champions League': 'Live UEFA Champions League',
  'UEFA Europa League': 'Live UEFA Europa League',
  'UEFA Europa Conference League': 'Live UEFA Conference League',
};

// ================== CACHE ==================
function getCache() {
  try {
    if (fs.existsSync(CONFIG.CACHE_FILE)) {
      const data = JSON.parse(fs.readFileSync(CONFIG.CACHE_FILE, 'utf8'));
      if (Date.now() - data.timestamp < CONFIG.CACHE_EXPIRY * 1000) {
        return data.channels;
      }
    }
  } catch (e) {}
  return null;
}

function saveCache(channels) {
  try {
    fs.writeFileSync(CONFIG.CACHE_FILE, JSON.stringify({
      timestamp: Date.now(),
      channels
    }));
  } catch (e) {}
}

// ================== HELPERS ==================
const normCache = new Map();

function normalize(s) {
  if (normCache.has(s)) return normCache.get(s);
  const nfd = s.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
  normCache.set(s, nfd);
  return nfd;
}

function similarity(a, b) {
  if (a === b) return 1;
  if (!a || !b) return 0;
  
  const lenA = a.length, lenB = b.length;
  if (Math.abs(lenA - lenB) > Math.max(lenA, lenB) * 0.3) return 0;
  
  const dp = Array(lenB + 1).fill(0).map((_, i) => i);
  
  for (let i = 1; i <= lenA; i++) {
    let prev = dp[0];
    dp[0] = i;
    
    for (let j = 1; j <= lenB; j++) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      const tmp = dp[j];
      dp[j] = Math.min(
        dp[j] + 1,
        dp[j - 1] + 1,
        prev + cost
      );
      prev = tmp;
    }
  }
  
  return 1 - (dp[lenB] / Math.max(lenA, lenB));
}

function extractPrefixAndName(name) {
  const lower = name.toLowerCase();
  const patterns = [
    /^\|\s*([a-z]{2,3})\s*\|\s*/i,
    /^([a-z]{2,3})\:\s*/i,
    /^([a-z]{2,3})\s*-\s*/i,
    /^([a-z]{2,3})\|\s*/i,
    /^\[([a-z]{2,3})\]\s*/i,
    /^\(([a-z]{2,3})\)\s*/i,
  ];
  
  for (const pat of patterns) {
    const match = lower.match(pat);
    if (match) {
      const code = match[1];
      if (COUNTRY_CODES.has(code)) {
        const remaining = lower.slice(match[0].length).replace(/^[\|:\-\s]+/, '').trim();
        return [code, remaining];
      }
    }
  }
  return [null, lower.replace(/^[\|\s:\-]+/, '').trim()];
}

function normalizeChannelName(name) {
  const [, cleaned] = extractPrefixAndName(name);
  return cleaned
    .replace(/\b(hd|uhd|8k|4k|fhd|sd|tv|channel|network|premium|extra|plus|max|stream|live|online|vip|ppv|hevc|full hd|ultra hd)\b/gi, '')
    .replace(/plus/g, '+')
    .replace(/\s+and\s+/gi, ' & ')
    .replace(/[^\w\s\+]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function isChannelMatch(ch1, ch2, league = null) {
  const [code1, clean1] = extractPrefixAndName(ch1);
  const [code2, clean2] = extractPrefixAndName(ch2);
  const norm1 = normalizeChannelName(clean1);
  const norm2 = normalizeChannelName(clean2);
  
  const threshold = league === 'Tennis' ? 0.85 : 0.92;
  
  if (norm1 === norm2) return true;
  if (norm1.length <= 3 || norm2.length <= 3) return norm1 === norm2;
  if (code1 && code2 && code1 !== code2) return false;
  
  return similarity(norm1, norm2) >= threshold;
}

function formatVnTime(timestamp) {
  const dt = new Date(timestamp * 1000);
  return dt.toLocaleString('vi-VN', {
    timeZone: 'Asia/Ho_Chi_Minh',
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: true
  });
}

function isFootballAllowed(league, matchName) {
  if (!ALLOWED_LEAGUES.has(league)) return false;
  if (ALLOWED_TEAMS[league]) {
    const matchLower = matchName.toLowerCase();
    return Array.from(ALLOWED_TEAMS[league]).some(t => matchLower.includes(t));
  }
  return true;
}

// ================== HTTP ==================
function fetchJson(url) {
  return new Promise((resolve) => {
    const protocol = url.startsWith('https') ? https : http;
    const options = {
      timeout: 10000,
      headers: { 'User-Agent': CONFIG.USER_AGENT }
    };
    
    protocol.get(url, options, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try {
          resolve(JSON.parse(data));
        } catch (e) {
          resolve(null);
        }
      });
    }).on('error', () => resolve(null));
  });
}

function fetchText(url) {
  return new Promise((resolve) => {
    const protocol = url.startsWith('https') ? https : http;
    const options = {
      timeout: 15000,
      headers: { 'User-Agent': CONFIG.USER_AGENT }
    };
    
    protocol.get(url, options, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => resolve(data));
    }).on('error', () => resolve(null));
  });
}

// ================== M3U PARSER ==================
function parseM3u(content) {
  const channels = [];
  const lines = content.split('\n');
  let i = 0;
  
  while (i < lines.length) {
    const line = lines[i].trim();
    
    if (line.startsWith('#EXTINF')) {
      if (line.includes('###')) {
        i++;
        continue;
      }
      
      const params = {};
      for (const [k, v] of line.matchAll(/([a-zA-Z-]+)="([^"]*)"/g)) {
        params[k[1].toLowerCase()] = k[2];
      }
      
      const parts = line.split(',');
      const name = parts.length > 1 ? parts.pop().trim() : 'Unknown';
      
      if (name.includes('###')) {
        i++;
        continue;
      }
      
      const extra = [];
      i++;
      
      while (i < lines.length && !lines[i].trim().startsWith('http')) {
        const extraLine = lines[i].trim();
        if (extraLine.startsWith('#EXTVLCOPT') || extraLine.startsWith('#')) {
          extra.push(extraLine);
        }
        i++;
      }
      
      if (i < lines.length && lines[i].trim().startsWith('http')) {
        const url = lines[i].trim();
        channels.push({
          name,
          url,
          params,
          extra: extra.length > 0 ? extra : null
        });
      }
      i++;
    } else {
      i++;
    }
  }
  
  return channels;
}

// ================== PARSERS ==================
async function parseFootonsat(data, startTs, endTs) {
  const games = [];
  if (!data?.footonsat || !Array.isArray(data.footonsat)) return games;
  
  const items = data.footonsat;
  let i = 0;
  
  while (i < items.length) {
    const item = items[i];
    if (!item.match || !item.time || !item.date) {
      i++;
      continue;
    }
    
    const compet = (item.compet || '').toLowerCase();
    let league = null;
    
    for (const [key, val] of Object.entries(LEAGUE_MAPPING)) {
      if (compet.includes(key)) {
        league = val;
        break;
      }
    }
    
    if (!league) {
      i++;
      continue;
    }
    
    try {
      const dt = new Date(`${item.date}T${item.time}Z`);
      const kickUtc = Math.floor(dt.getTime() / 1000);
      
      if (kickUtc < startTs || kickUtc > endTs) {
        i++;
        continue;
      }
      
      const matchName = item.match.trim();
      if (!isFootballAllowed(league, matchName)) {
        i++;
        continue;
      }
      
      const channels = [];
      let j = i + 1;
      
      while (j < items.length) {
        const next = items[j];
        if (next.match && next.time && next.date) break;
        if (next.channel) {
          channels.push({
            country_code: null,
            channel_name: next.channel.replace(/[📺]/g, '').trim()
          });
        }
        j++;
      }
      
      if (channels.length > 0) {
        games.push({
          league,
          match: matchName,
          kick_utc: kickUtc,
          time: formatVnTime(kickUtc),
          channels,
          source: 'footonsat'
        });
      }
      
      i = j;
    } catch (e) {
      i++;
    }
  }
  
  return games;
}

async function parseLove4vn(data, startTs, endTs) {
  const games = [];
  if (!data?.days) return games;
  
  for (const dayInfo of Object.values(data.days)) {
    if (!dayInfo.games) continue;
    
    for (const game of dayInfo.games) {
      const kickUtc = game.kick_utc;
      if (!kickUtc || kickUtc < startTs || kickUtc > endTs) continue;
      
      const league = game.league || '';
      let matchName = (game.match || '').trim();
      
      if (league !== 'Tennis' && !isFootballAllowed(league, matchName)) continue;
      if (league === 'Tennis' && !matchName) matchName = 'Tennis match';
      
      const channels = [];
      for (const entry of (game.tv_channels || [])) {
        for (const chName of (entry.channels || [])) {
          if (chName) {
            channels.push({
              country_code: null,
              channel_name: chName
            });
          }
        }
      }
      
      if (channels.length > 0) {
        games.push({
          league,
          match: matchName,
          kick_utc: kickUtc,
          time: game.time || formatVnTime(kickUtc),
          channels,
          source: 'love4vn'
        });
      }
    }
  }
  
  return games;
}

// ================== VALIDATION ==================
function validateUrl(url) {
  return new Promise((resolve) => {
    if (url.startsWith('udp://')) {
      resolve([true, null]);
      return;
    }
    
    const urlLower = url.toLowerCase();
    if (urlLower.includes('cinehub24.com') || urlLower.endsWith('.mp4')) {
      resolve([false, 'Blacklisted']);
      return;
    }
    
    const protocol = url.startsWith('https') ? https : http;
    const options = {
      timeout: CONFIG.VALIDATION_TIMEOUT,
      headers: {
        'User-Agent': CONFIG.USER_AGENT,
        'Range': 'bytes=0-1024'
      }
    };
    
    protocol.get(url, options, (res) => {
      let body = '';
      res.on('data', chunk => body += chunk.toString().slice(0, 5000));
      res.on('end', () => {
        if ([200, 206].includes(res.statusCode)) {
          if (url.includes('.m3u8')) {
            const valid = body.includes('#EXTM3U') || body.includes('#EXTINF');
            resolve([valid, valid ? null : 'Invalid HLS']);
          } else {
            resolve([true, null]);
          }
        } else {
          resolve([false, `HTTP ${res.statusCode}`]);
        }
      });
    }).on('error', () => resolve([false, 'Error']));
    
    setTimeout(() => resolve([false, 'Timeout']), CONFIG.VALIDATION_TIMEOUT);
  });
}

async function validateBatch(events) {
  if (events.length === 0) return [];
  
  console.log(`\n🔬 Kiểm tra ${events.length} kênh...`);
  
  const batchSize = CONFIG.VALIDATION_CONCURRENT;
  const valid = [];
  
  for (let i = 0; i < events.length; i += batchSize) {
    const batch = events.slice(i, i + batchSize);
    const results = await Promise.all(
      batch.map(ev => validateUrl(ev.channel.url))
    );
    
    for (let j = 0; j < batch.length; j++) {
      if (results[j][0]) valid.push(batch[j]);
    }
  }
  
  console.log(`   ✅ ${valid.length}/${events.length} hợp lệ`);
  return valid;
}

// ================== MAIN ==================
async function main() {
  console.log('🔄 Bắt đầu lấy lịch...');
  const start = Date.now();
  
  const nowUtc = Math.floor(Date.now() / 1000);
  const startTs = nowUtc - 7200;
  const endTs = nowUtc + 86400;
  
  // Fetch APIs
  console.log('📡 Tải APIs...');
  const [footonsatResults, love4vnData] = await Promise.all([
    Promise.all(FOOTONSAT_URLS.map(fetchJson)),
    fetchJson(LOVE4VN_URL)
  ]);
  
  // Parse
  let allGames = [];
  for (const data of footonsatResults) {
    if (data) {
      const games = await parseFootonsat(data, startTs, endTs);
      allGames.push(...games);
    }
  }
  
  const love4vnGames = await parseLove4vn(love4vnData, startTs, endTs);
  allGames.push(...love4vnGames);
  
  console.log(`✅ Tổng: ${allGames.length} trận`);
  
  if (allGames.length === 0) {
    console.log('⚠️ Không có trận nào.');
    return;
  }
  
  // Load M3U
  console.log('📥 Tải M3U...');
  let channels = getCache();
  
  if (!channels) {
    let m3uLinks = [];
    try {
      const content = fs.readFileSync(CONFIG.M3U_LIST_FILE, 'utf8');
      m3uLinks = content.split('\n')
        .map(l => l.trim())
        .filter(l => l.startsWith('http'));
    } catch (e) {
      console.log('   ⚠️ Không tìm thấy M3U_list.txt');
    }
    
    console.log(`   📋 ${m3uLinks.length} URLs`);
    
    const allChannels = [];
    const batchSize = CONFIG.M3U_FETCH_WORKERS;
    
    for (let i = 0; i < m3uLinks.length; i += batchSize) {
      const batch = m3uLinks.slice(i, i + batchSize);
      const contents = await Promise.all(batch.map(fetchText));
      
      for (const content of contents) {
        if (content) {
          const parsed = parseM3u(content);
          allChannels.push(...parsed.filter(ch => 
            !ch.name.match(/\b(sd|360p|480p|576p|low)\b/i)
          ));
        }
      }
      
      console.log(`      ${Math.min(i + batchSize, m3uLinks.length)}/${m3uLinks.length}`);
    }
    
    channels = Array.from(new Map(allChannels.map(ch => [ch.url, ch])).values());
    saveCache(channels);
  } else {
    console.log(`   ✅ Từ cache: ${channels.length} kênh`);
  }
  
  console.log(`   ✅ Tổng: ${channels.length} kênh`);
  
  // Match
  console.log('🔄 Match kênh...');
  const liveEvents = [];
  const usedUrls = new Set();
  
  for (const game of allGames) {
    for (const chInfo of game.channels) {
      const targetName = chInfo.channel_name;
      const matching = channels.filter(ch => 
        isChannelMatch(targetName, ch.name, game.league)
      );
      // 🔍 Log chi tiết quá trình match
console.log(`\n🎯 Tìm kênh cho: "${targetName}" (${game.league})`);

const matching = channels.filter(ch => {
  const isMatch = isChannelMatch(targetName, ch.name, game.league);
  if (isMatch) {
    console.log(`   ✅ Khớp: "${ch.name}"`);
  }
  return isMatch;
});

if (matching.length === 0) {
  console.log(`   ❌ Không tìm thấy kênh phù hợp.`);
}
      if (matching.length > 0) {
        const ch = matching[0];
        console.log(`   📺 Chọn: "${ch.name}" (${ch.url.substring(0, 60)}...)`);
        if (!usedUrls.has(ch.url)) {
          usedUrls.add(ch.url);
          liveEvents.push({
            datetime: new Date(game.kick_utc * 1000),
            name: `${game.time} | ${game.match} (${ch.name})`,
            channel: ch,
            league: game.league
          });
        }
      }
    }
  }
  
  liveEvents.sort((a, b) => a.datetime - b.datetime);
  
  // Validate
  let finalEvents = liveEvents;
  if (!SKIP_VALIDATION) {
    finalEvents = await validateBatch(liveEvents);
  }
  
  // Write output
  const m3uLines = ['#EXTM3U'];
  for (const ev of finalEvents) {
    const ch = ev.channel;
    const group = LEAGUE_GROUP_NAME[ev.league] || 'Live Football';
    
    let extinf = `#EXTINF:-1 tvg-id="${ch.params['tvg-id'] || ''}" group-title="${group}"`;
    if (ch.params['tvg-logo']) {
      extinf += ` tvg-logo="${ch.params['tvg-logo']}"`;
    }
    extinf += `,${ev.name}`;
    
    m3uLines.push(extinf);
    if (ch.extra) m3uLines.push(...ch.extra);
    m3uLines.push(ch.url);
  }
  
  fs.writeFileSync(CONFIG.LIVE_M3U, m3uLines.join('\n'));
  
  const elapsed = (Date.now() - start) / 1000;
  console.log(`\n🎉 HOÀN THÀNH! ${finalEvents.length} kênh trong ${elapsed.toFixed(1)}s`);
}

main().catch(console.error);
