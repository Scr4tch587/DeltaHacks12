# ReelJobs

## Inspiration

Job hunting sucks. You scroll through endless walls of text, copy-paste the same resume into a dozen forms, and still hear nothing back. Meanwhile, we spend hours on TikTok and Instagram Reels consuming content effortlessly.

We asked ourselves: **what if finding your next job felt as easy as scrolling through Reels?**

Gen Z and millennials already consume information through short-form video. Why should job discovery be stuck in the 2010s? ReelJobs brings job listings into the format we actually enjoy consuming.

## What it does

ReelJobs transforms job listings into engaging short-form vertical videos. Instead of reading through job descriptions, you swipe through 15-30 second video summaries that capture the essence of each role.

**Key features:**
- **Swipe-to-discover feed** - TikTok-style vertical video interface for browsing jobs
- **Semantic search** - Tell us what you're looking for in natural language ("remote Python jobs at startups") and our AI finds relevant matches
- **Smart tracking** - We remember what you've seen so you never get the same job twice
- **One-tap apply** - When you find a job you love, our AI can auto-fill applications for you

## How we built it

**Architecture:**
- **3 Python microservices** (FastAPI) handling authentication, job scraping, and video delivery
- **Expo React Native** mobile app with HLS video streaming
- **MongoDB Atlas** with vector search for semantic job matching
- **Google Gemini** for generating embeddings and powering our AI features
- **DigitalOcean Spaces CDN** for low-latency video delivery worldwide

**Video Pipeline:**
We built a custom pipeline that takes job descriptions and generates engaging videos:
1. LLM generates a script with character dialogue
2. Fish.audio converts text to speech with emotion
3. FFmpeg composites everything with karaoke-style captions
4. Videos are transcoded to HLS and served via CDN

**Job Automation:**
Our headless service uses Playwright to scrape Greenhouse job boards and can even auto-fill applications using AI-generated responses tailored to each job.

## Challenges we ran into

**HLS streaming on mobile** - Getting expo-video to play HLS streams reliably took significant debugging. We had to carefully manage player lifecycle, handle edge cases around visibility changes, and optimize prefetching to make scrolling feel smooth.

**Vector search tuning** - MongoDB's vector search is powerful but getting the right balance of `numCandidates` vs `limit` while filtering seen jobs required iteration. Too few candidates and relevant jobs get missed; too many and latency suffers.

**Video generation at scale** - Our initial video pipeline was slow. We added aggressive caching at each step (scripts, audio, timestamps) so regenerating just the video composition doesn't require re-running expensive API calls.

**Form automation** - Greenhouse forms are surprisingly complex with React-Select dropdowns, conditional fields, and various input types. Our Playwright automation had to handle all these edge cases gracefully.

## Accomplishments that we're proud of

- **Sub-second video starts** - HLS + CDN edge caching means videos begin playing almost instantly
- **Seamless infinite scroll** - Smart prefetching and player management makes the feed feel native
- **Full-stack AI integration** - Gemini powers search, content generation, and application assistance
- **Production-ready architecture** - Docker Compose deployment, health checks, proper error handling

## What we learned

- **HLS is the way** - For mobile video, HLS with CDN beats serving raw MP4s every time
- **Vector search is magic** - Semantic search with embeddings creates a much better UX than keyword matching
- **Caching is everything** - In AI pipelines, cache aggressively at every step
- **Mobile video is hard** - Player lifecycle management, audio sessions, and performance optimization are non-trivial

## What's next for ReelJobs

- **Personalized recommendations** - Learn from swipe patterns to surface better matches
- **Company culture videos** - Partner with companies to include authentic team content
- **Interview prep** - AI-powered mock interviews based on the job you're applying to
- **Salary insights** - Integrate compensation data to show expected ranges
- **Browser extension** - Bring the ReelJobs experience to LinkedIn and other job boards
