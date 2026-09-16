/** Supabase is the sole owner of persisted sessions and token refresh. */
class AuthSession {
  constructor() {
    this.client = null;
  }

  async initialize() {
    const response = await fetch('/auth/config', { cache: 'no-store' });
    const config = await response.json();
    if (!response.ok) throw new Error(config.error?.message || 'Configuração de login indisponível.');
    if (!window.supabase) throw new Error('Não foi possível carregar o serviço de login. Recarregue a página.');
    this.client = window.supabase.createClient(config.url, config.publicKey, {
      auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true }
    });
    this.client.auth.onAuthStateChange((event, session) => {
      window.apiClient.setToken(session?.access_token);
      // Run outside the Supabase callback to avoid holding its session lock.
      setTimeout(() => window.dispatchEvent(new CustomEvent('23e:session', {
        detail: { event, session }
      })), 0);
    });
    const { data, error } = await this.client.auth.getSession();
    if (error) throw error;
    window.apiClient.setToken(data.session?.access_token);
    return data.session;
  }

  async getToken() {
    if (!this.client) return null;
    const { data, error } = await this.client.auth.getSession();
    if (error) throw error;
    window.apiClient.setToken(data.session?.access_token);
    return data.session?.access_token || null;
  }

  async signIn(email, password) {
    if (!this.client) throw new Error('Login indisponível. Recarregue a página.');
    const { data, error } = await this.client.auth.signInWithPassword({ email, password });
    if (error) throw error;
    window.apiClient.setToken(data.session?.access_token);
    return data.session;
  }

  async signInWithGoogle() {
    if (!this.client) throw new Error('Login indisponível. Recarregue a página.');
    const { error } = await this.client.auth.signInWithOAuth({
      provider: 'google', options: { redirectTo: window.location.origin + '/' }
    });
    if (error) throw error;
  }

  async signOut() {
    if (this.client) {
      const { error } = await this.client.auth.signOut({ scope: 'local' });
      if (error) throw error;
    }
    window.apiClient.setToken(null);
    window.apiClient.setCompany(null);
  }
}
window.authSession = new AuthSession();
