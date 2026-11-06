<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import WelcomeOrbit from '@/components/WelcomeOrbit.vue'
import BlogArtwork from '@/components/BlogArtwork.vue'
import { blogPosts, readingMinutes } from '@/content/blog'

const route = useRoute()
const categories = ['全部', '技术', '设计', '生活'] as const
const category = ref<(typeof categories)[number]>('全部')
const query = ref('')
const featured = blogPosts[0]!
const isArticle = computed(() => route.name === 'blog-article')
const article = computed(() => blogPosts.find((post) => post.slug === route.params.slug))
const filteredPosts = computed(() => {
  const search = query.value.trim().toLocaleLowerCase()
  return blogPosts.filter((post) =>
    (category.value === '全部' || post.category === category.value) &&
    `${post.title} ${post.excerpt} ${post.category}`.toLocaleLowerCase().includes(search))
})
const months = [...new Set(blogPosts.map((post) => post.date.slice(0, 7)))]
const nextArticle = computed(() => {
  const index = blogPosts.findIndex((post) => post.slug === article.value?.slug)
  return blogPosts[(index + 1) % blogPosts.length]!
})
const fontSize = ref(18)
const readProgress = ref(0)
const copyStatus = ref('')
let copyTimer: ReturnType<typeof setTimeout> | undefined
let previousTitle = ''
let scrollFrame = 0

function updateProgress() {
  if (scrollFrame) return
  scrollFrame = requestAnimationFrame(() => {
    const content = document.getElementById('article-body')
    if (content) {
      const top = content.getBoundingClientRect().top + window.scrollY
      const distance = Math.max(1, content.offsetHeight - window.innerHeight + 180)
      readProgress.value = Math.min(100, Math.max(0, (window.scrollY - top + 120) / distance * 100))
    }
    scrollFrame = 0
  })
}

async function syncPage() {
  document.title = isArticle.value
    ? `${article.value?.title ?? '文章未找到'} · 白切粥`
    : '白切粥 · 慢慢想，好好写'
  copyStatus.value = ''
  await nextTick()
  const target = route.hash ? document.getElementById(decodeURIComponent(route.hash.slice(1))) : null
  if (target) target.scrollIntoView()
  else window.scrollTo({ top: 0, behavior: 'instant' })
  if (isArticle.value) document.getElementById('article-title')?.focus({ preventScroll: true })
  updateProgress()
}

async function copyLink() {
  if (copyTimer) clearTimeout(copyTimer)
  try {
    if (!navigator.clipboard) throw new Error('Clipboard unavailable')
    await navigator.clipboard.writeText(window.location.href)
    copyStatus.value = '链接已复制'
  } catch {
    copyStatus.value = '请复制浏览器地址栏中的文章链接'
  }
  copyTimer = setTimeout(() => { copyStatus.value = '' }, 4000)
}

function resetFilters() {
  category.value = '全部'
  query.value = ''
}

onMounted(() => {
  previousTitle = document.title
  void syncPage()
  window.addEventListener('scroll', updateProgress, { passive: true })
  window.addEventListener('resize', updateProgress)
})
watch(() => route.fullPath, syncPage)
watch(fontSize, async () => { await nextTick(); updateProgress() })
onUnmounted(() => {
  document.title = previousTitle
  window.removeEventListener('scroll', updateProgress)
  window.removeEventListener('resize', updateProgress)
  if (scrollFrame) cancelAnimationFrame(scrollFrame)
  if (copyTimer) clearTimeout(copyTimer)
})
</script>

<template>
  <div class="blog-page">
    <a class="skip-link" href="#blog-content">跳到正文</a>
    <div v-if="isArticle && article" class="reading-progress" :style="{ width: `${readProgress}%` }" aria-hidden="true"></div>
    <header class="blog-header blog-container">
      <RouterLink class="blog-brand" to="/blog" aria-label="白切粥博客首页">
        <span class="brand-symbol" aria-hidden="true">✳</span>
        <span>白切粥<small>A PERSONAL JOURNAL</small></span>
      </RouterLink>
      <nav aria-label="博客导航">
        <RouterLink to="/blog#articles" :class="{ active: !isArticle && (!route.hash || route.hash === '#articles') }">文章</RouterLink>
        <RouterLink to="/blog#archive" :class="{ active: route.hash === '#archive' }">归档</RouterLink>
        <RouterLink to="/blog#about" :class="{ active: route.hash === '#about' }">关于</RouterLink>
      </nav>
      <span class="header-signature">保持好奇，慢慢生长 <span aria-hidden="true">↗</span></span>
    </header>

    <main id="blog-content" tabindex="-1" class="blog-container">
      <template v-if="!isArticle">
        <section class="blog-hero" aria-labelledby="hero-title">
          <div class="hero-copy">
            <p class="eyebrow"><span class="status-dot"></span> NOTES FROM MY LITTLE UNIVERSE</p>
            <h1 id="hero-title">慢慢想，<br />好好<span>写。</span></h1>
            <p class="hero-description">在技术与日常之间，留一处思考的空地。<br />记录微小的发现，也收藏那些尚未有答案的问题。</p>
            <a class="explore-link" href="#articles"><span class="circle-arrow" aria-hidden="true">↓</span> 随意翻翻 <span class="mono">EXPLORE THE JOURNAL</span></a>
          </div>
          <div class="hero-orbit"><WelcomeOrbit :entered="false" /></div>
          <span class="hero-side-note mono">THINK DEEPLY. LIVE SIMPLY.</span>
          <div class="hero-bottom"><span>白切粥的文字宇宙</span><span class="mono">IDEAS / CRAFT / EVERYDAY</span></div>
        </section>

        <section class="featured-section" aria-labelledby="featured-title">
          <div class="section-label"><span class="eyebrow">01 / EDITOR'S PICK</span><span>置顶随笔</span></div>
          <RouterLink :to="`/blog/${featured.slug}`" class="featured-link">
            <div class="featured-copy">
              <div class="post-meta"><span>{{ featured.category }}</span><span>{{ featured.date.replaceAll('-', '.') }}</span><span>{{ readingMinutes(featured) }} 分钟阅读</span></div>
              <h2 id="featured-title">给好奇心，<br />留一点空白<span class="gold">。</span></h2>
              <p>{{ featured.excerpt }}</p>
              <span class="text-link">读这篇文章 <span aria-hidden="true">↗</span></span>
            </div>
            <div class="featured-art"><BlogArtwork :motif="featured.motif" /><span class="featured-art-caption">STAY<br /><em>curious.</em></span></div>
          </RouterLink>
        </section>

        <section id="articles" class="journal-section" aria-labelledby="journal-title">
          <div class="section-heading"><div><p class="eyebrow">02 / THE JOURNAL</p><h2 id="journal-title">最近写下的<span class="title-dot">。</span></h2></div><span class="sample-label">示例文章 · {{ blogPosts.length }} 篇</span></div>
          <div class="journal-layout">
            <div class="journal-main">
              <div class="journal-controls">
                <div class="category-filters" role="group" aria-label="文章主题">
                  <button v-for="item in categories" :key="item" type="button" :aria-pressed="category === item" :class="{ selected: category === item }" @click="category = item">{{ item }}</button>
                </div>
                <label class="search-box"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 5 5" /></svg><input v-model="query" type="search" aria-label="搜索文章" placeholder="搜索一个念头…" /></label>
              </div>
              <p class="sr-only" role="status">找到 {{ filteredPosts.length }} 篇文章</p>
              <div v-if="filteredPosts.length" class="post-list">
                <RouterLink v-for="post in filteredPosts" :key="post.slug" :to="`/blog/${post.slug}`" class="post-row">
                  <div class="post-thumbnail"><BlogArtwork :motif="post.motif" /></div>
                  <div class="post-row-copy"><div class="post-meta"><span>{{ post.category }}</span><time :datetime="post.date">{{ post.date.replaceAll('-', '.') }}</time></div><h3>{{ post.title }}</h3><p>{{ post.excerpt }}</p><span class="read-time">{{ readingMinutes(post) }} 分钟阅读</span></div>
                  <span class="row-arrow" aria-hidden="true">↗</span>
                </RouterLink>
              </div>
              <div v-else class="empty-state"><span aria-hidden="true">∅</span><h3>这个念头，还没有写下。</h3><p>换一个关键词，或看看其他主题。</p><button type="button" class="text-link" @click="resetFilters">查看全部文章 ↗</button></div>
            </div>

            <aside class="journal-sidebar">
              <section id="about" class="about-card" aria-labelledby="about-title"><div class="author-seal" aria-hidden="true">粥<span>✳</span></div><p class="eyebrow">THE PERSON BEHIND THE WORDS</p><h2 id="about-title">你好，我是白切粥。</h2><p>这里是一块安静的自留地，<br />用文字整理想法，<br />用好奇心连接世界。</p><div class="about-divider"></div><p class="about-motto">不追赶所有声音，<br />只认真写下自己的回响。</p><span class="handwritten">白切粥</span></section>
              <div class="margin-note"><span class="eyebrow">A SMALL REMINDER</span><p>“不必每一次出发，<br />都知道要去哪里。”</p><span class="mono">LEAVE ROOM FOR THE UNKNOWN</span></div>
            </aside>
          </div>
        </section>

        <section id="archive" class="archive-section" aria-labelledby="archive-title"><div class="section-heading"><div><p class="eyebrow">03 / THROUGH TIME</p><h2 id="archive-title">时间的脚注<span class="title-dot">。</span></h2></div><span class="sample-label">把零散的思绪，串成一条线。</span></div><div class="archive-grid"><section v-for="month in months" :key="month" class="archive-month"><h3>{{ month.replace('-', ' / ') }}<span>{{ blogPosts.filter(post => post.date.startsWith(month)).length }} 篇</span></h3><RouterLink v-for="post in blogPosts.filter(item => item.date.startsWith(month))" :key="post.slug" :to="`/blog/${post.slug}`"><time :datetime="post.date">{{ post.date.slice(-2) }}</time><span>{{ post.title }}</span><span aria-hidden="true">↗</span></RouterLink></section></div></section>
        <section class="closing-note"><span class="closing-star" aria-hidden="true">✳</span><p>文字是坐标，<br />好奇心是<span>方向。</span></p><a href="#hero-title" class="text-link">回到起点 ↑</a></section>
      </template>

      <article v-else-if="article" class="article-page">
        <RouterLink to="/blog#articles" class="back-link">← 返回文章列表</RouterLink>
        <header class="article-heading"><div class="post-meta"><span>{{ article.category }}</span><time :datetime="article.date">{{ article.date.replaceAll('-', '.') }}</time><span>{{ readingMinutes(article) }} 分钟阅读</span></div><h1 id="article-title" tabindex="-1">{{ article.title }}</h1><p class="article-deck">{{ article.excerpt }}</p><div class="article-byline"><span class="author-mini" aria-hidden="true">粥</span><span>白切粥 <span class="sample-label">/ 示例随笔</span></span><div class="reading-actions"><button type="button" :aria-label="`当前字号 ${fontSize}，点击切换正文字号`" @click="fontSize = fontSize === 22 ? 18 : fontSize + 2">Aa <span>{{ fontSize }}</span></button><button type="button" @click="copyLink">复制链接 ↗</button></div></div><p class="copy-status" role="status">{{ copyStatus }}</p></header>
        <div class="article-cover"><BlogArtwork :motif="article.motif" /><span class="cover-title mono">A NOTE FROM<br />MY LITTLE UNIVERSE.</span></div>
        <div class="reading-layout"><div id="article-body" class="article-body" :style="{ fontSize: `${fontSize}px` }"><p class="article-opening">{{ article.excerpt }}</p><template v-for="(section, index) in article.sections" :key="section.title"><section :id="`section-${index}`"><h2><span class="mono">0{{ index + 1 }}</span>{{ section.title }}</h2><p v-for="paragraph in section.paragraphs" :key="paragraph">{{ paragraph }}</p></section><blockquote v-if="index === 0">{{ article.quote }}</blockquote></template><div class="article-end"><span aria-hidden="true">✳</span><p>感谢你读到这里。<br /><span>愿我们一直保有提问的热情。</span></p></div></div><aside class="article-toc"><p class="eyebrow">IN THIS NOTE</p><a v-for="(section, index) in article.sections" :key="section.title" :href="`#section-${index}`"><span>0{{ index + 1 }}</span>{{ section.title }}</a><div class="toc-rule"></div><RouterLink to="/blog#articles">← 浏览所有文章</RouterLink></aside></div>
        <RouterLink :to="`/blog/${nextArticle.slug}`" class="next-article"><div><p class="eyebrow">KEEP WANDERING / 继续阅读</p><h2>{{ nextArticle.title }}</h2></div><span aria-hidden="true">↗</span></RouterLink>
      </article>

      <section v-else class="missing-article"><span class="eyebrow">404 / UNCHARTED TERRITORY</span><h1 id="article-title" tabindex="-1">这一页，还没有写下。</h1><p>文章可能已移走，或链接有误。去首页看看其他故事吧。</p><RouterLink to="/blog" class="text-link">返回博客首页 ↗</RouterLink></section>
    </main>

    <footer class="blog-footer blog-container"><RouterLink to="/blog" class="footer-brand">白切粥 <span aria-hidden="true">✳</span></RouterLink><p>一个人的记录，也是一扇向外的窗。</p><span class="mono">© {{ new Date().getFullYear() }} 白切粥<br /><span class="sample-label">文章为示例内容，可替换为真实创作</span></span></footer>
  </div>
</template>

<style scoped src="../styles/blog.css"></style>
