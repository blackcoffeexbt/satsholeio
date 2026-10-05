window.app = Vue.createApp({
  mixins: [windowMixin],
  delimiters: ['${', '}'],
  data() {
    return {
      aggressionOptions: ['Passive','Timid','Cautious','Reserved','Balanced','Assertive','Aggressive','Fierce','Ruthless','Relentless'].map((name,index)=>({label:(index+1)+'. '+name,value:index+1})),
      walletId: null,
      busy: false,
      error: '',
      configured: false,
      operations: {competitions: [], payments: []},
      review: {runs: [], audit: [], page: 0},
      reviewCompetition: null,
      reviewPage: 0,
      inspection: null,
      inspectionOpen: false,
      actionOpen: false,
      action: null,
      actionReason: '',
      actionAddress: '',
      actionError: '',
      config: {enabled: true, game_price: 25, free_runs: 3, duration: 120,
        ai_count: 8, competitor_aggression: 5, death_penalty: 20, invoice_expiry: 600, ready_expiry: 3600,
        undistributed_policy: 'carry', automatic_payouts: false, settlement_delay: 3600, leaderboard_enabled: false, leaderboard_price: 250, prize_percentage: 80,
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
        this.operations = await this.gameRequest('GET', 'operations')
        await this.loadReview()
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
    async loadReview() {
      const query = new URLSearchParams({page: this.reviewPage})
      if (this.reviewCompetition) query.set('competition_id', this.reviewCompetition)
      this.review = await this.gameRequest('GET', 'review?' + query)
    },
    async changeReviewPage(delta) {
      this.reviewPage = Math.max(0, this.reviewPage + delta)
      try { await this.loadReview() } catch (error) { this.error = error.message }
    },
    requestAction(title, path, data = {}, address = null) {
      this.action = {title, path, data, request_id: crypto.randomUUID(), repair: address !== null}
      this.actionReason = ''; this.actionAddress = address || ''; this.actionError = ''
      this.actionOpen = true
    },
    async performAction() {
      if (this.actionReason.trim().length < 3) {
        this.actionError = 'Enter a reason for this action.'; return
      }
      this.busy = true; this.actionError = ''
      const data = {...this.action.data, request_id: this.action.request_id, reason: this.actionReason.trim()}
      if (this.action.repair) data.lightning_address = this.actionAddress.trim()
      try {
        await this.gameRequest('POST', this.action.path, data)
        this.actionOpen = false
        await this.load()
        this.$q.notify({type: 'positive', message: 'Operator action recorded'})
      } catch (error) { this.actionError = error.message }
      finally { this.busy = false }
    },
    async inspectRun(id) {
      this.busy = true
      try { this.inspection = await this.gameRequest('GET', 'review/runs/' + id); this.inspectionOpen = true }
      catch (error) { this.error = error.message }
      finally { this.busy = false }
    },
    async inspectAudit(id) {
      try { this.inspection = await this.gameRequest('GET', 'review/audit/' + id); this.inspectionOpen = true }
      catch (error) { this.error = error.message }
    },
    async replayRun(id) {
      this.busy = true
      try { this.inspection = await this.gameRequest('POST', 'review/runs/' + id + '/replay'); this.inspectionOpen = true }
      catch (error) { this.error = error.message }
      finally { this.busy = false }
    },
    async downloadRun(id) {
      try {
        const data = await this.gameRequest('GET', 'review/runs/' + id + '/replay')
        const url = URL.createObjectURL(new Blob([JSON.stringify(data)], {type: 'application/json'}))
        const link = document.createElement('a'); link.href = url; link.download = 'satshole-' + id + '.json'; link.click()
        setTimeout(() => URL.revokeObjectURL(url), 1000)
      } catch (error) { this.error = error.message }
    },
    async pause() { this.config.enabled = false; await this.save() }
  }
})
