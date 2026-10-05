window.app = Vue.createApp({
  mixins: [windowMixin],
  delimiters: ['${', '}'],
  data() {
    return {
      walletId: null,
      busy: false,
      error: '',
      configured: false,
      config: {enabled: true, game_price: 25, free_runs: 3, duration: 120,
        ai_count: 8, death_penalty: 20, invoice_expiry: 600, ready_expiry: 3600,
        leaderboard_enabled: false, leaderboard_price: 250, prize_percentage: 80,
        first_percentage: 70, second_percentage: 20, third_percentage: 10,
        allow_free_entries: false, timezone: 'Europe/London', close_weekday: 6,
        close_hour: 21, close_minute: 0},
      metrics: {game_revenue: 0, prize_liability: 0, runs: []}
    }
  },
  async mounted() { await this.restoreWallet() },
  methods: {
    key(walletId = this.walletId) {
      return this.g.user.wallets.find(w => w.id === walletId)?.adminkey
    },
    async gameRequest(method, path, data, walletId = this.walletId) {
      const key = this.key(walletId)
      if (!key) throw Error('Select a wallet before saving.')
      const response = await fetch('/satshole/api/v1/game/' + path, {
        method,
        headers: {'X-Api-Key': key, 'Content-Type': 'application/json'},
        body: data ? JSON.stringify(data) : undefined
      })
      const result = await response.json()
      if (!response.ok) throw Error(typeof result.detail === 'string'
        ? result.detail : 'Check the settings values.')
      return result
    },
    async restoreWallet() {
      // Discover the saved wallet using only wallets this LNbits user owns.
      for (const wallet of this.g.user.wallets) {
        try {
          const saved = await this.gameRequest('GET', 'settings', undefined, wallet.id)
          if (saved.configured) {
            this.walletId = saved.wallet_id
            this.configured = true
            this.config = saved.config
            await this.load()
            return
          }
        } catch { /* Other wallets cannot access this game's configuration. */ }
      }
    },
    async load() {
      this.error = ''
      try {
        const saved = await this.gameRequest('GET', 'settings')
        this.configured = saved.configured
        // A paused, unconfigured public game is not a saved operator setting.
        if (saved.configured) this.config = saved.config
        this.metrics = await this.gameRequest('GET', 'metrics')
      } catch (error) { this.error = error.message }
    },
    async save() {
      this.busy = true
      this.error = ''
      try {
        const result = await this.gameRequest('PUT', 'settings', this.config)
        this.walletId = result.wallet_id
        this.config = result.config
        this.configured = true
        await this.load()
        if (!this.error) this.$q.notify({type: 'positive', message: 'Wallet and game settings saved'})
      } catch (error) { this.error = error.message }
      finally { this.busy = false }
    },
    async pause() { this.config.enabled = false; await this.save() }
  }
})
