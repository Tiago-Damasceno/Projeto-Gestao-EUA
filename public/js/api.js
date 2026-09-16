/**
 * Módulo Central de Comunicação com a API Flask — 23e Gestão
 */
const API_BASE_URL = window.location.origin + '/api/v1';

class ApiClient {
  constructor() {
    this.token = null;
    this.companyId = null;
    // Remove the old token store, which could contain encoded credentials.
    sessionStorage.removeItem('23e_token');
    localStorage.removeItem('23e_token');
  }

  setToken(token) {
    this.token = token || null;
  }

  setCompany(companyId) {
    this.companyId = companyId || null;
  }

  getToken() {
    return this.token;
  }

  async request(endpoint, options = {}) {
    const headers = {
      'Content-Type': 'application/json',
      ...(options.headers || {})
    };

    // Supabase owns session persistence and refresh; never trust a stale copy.
    const token = window.authSession ? await window.authSession.getToken() : this.token;
    if (token) headers['Authorization'] = `Bearer ${token}`;

    const url = new URL(`${API_BASE_URL}${endpoint}`);
    if (this.companyId && endpoint !== '/me' && endpoint !== '/companies' && endpoint !== '/organizations') {
      url.searchParams.set('company_id', this.companyId);
    }

    const config = {
      ...options,
      headers
    };

    try {
      const response = await fetch(url.toString(), config);
      const isJson = response.headers.get('content-type')?.includes('application/json');
      const data = isJson ? await response.json() : null;

      if (!response.ok) {
        const error = (data && data.error) ? data.error : { code: 'http_error', message: `Erro HTTP ${response.status}` };
        if (response.status === 401) {
          this.setToken(null);
          window.dispatchEvent(new CustomEvent('23e:unauthorized', { detail: error }));
        } else if (response.status === 403 && error.code === 'access_not_granted') {
          window.dispatchEvent(new CustomEvent('23e:access_denied', { detail: error }));
        }
        throw error;
      }

      return data;
    } catch (err) {
      if (err.message && !err.code) {
        throw { code: 'network_error', message: 'Falha de conexão com o servidor. Verifique se a API está online.' };
      }
      throw err;
    }
  }

  // Endpoints da API 23e Gestão
  getMe() {
    return this.request('/me');
  }

  getDashboardStats() {
    return this.request('/dashboard/stats');
  }

  getLeads(stage = null) {
    const query = stage ? `?stage=${encodeURIComponent(stage)}` : '';
    return this.request(`/leads${query}`);
  }

  createLead(data) {
    return this.request('/leads', {
      method: 'POST',
      body: JSON.stringify(data)
    });
  }

  updateLead(id, data) {
    return this.request(`/leads/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data)
    });
  }

  moveLeadStage(id, stage) {
    return this.request(`/leads/${id}/stage`, {
      method: 'POST',
      body: JSON.stringify({ stage })
    });
  }

  deleteLead(id) {
    return this.request(`/leads/${id}`, {
      method: 'DELETE'
    });
  }

  getConversations() {
    return this.request('/conversations');
  }

  getConversationMessages(conversationId) {
    return this.request(`/conversations/${conversationId}/messages`);
  }

  updateConversationAutomation(conversationId, data) {
    return this.request(`/conversations/${conversationId}/automation`, {
      method: 'PATCH',
      body: JSON.stringify(data)
    });
  }

  getCompanyAutomation() {
    return this.request('/company/automation');
  }

  updateCompanyAutomation(automation_enabled, reason = '') {
    return this.request('/company/automation', {
      method: 'PATCH',
      body: JSON.stringify({ automation_enabled, reason })
    });
  }

  completeOnboarding(data) {
    return this.request('/onboarding/complete', {
      method: 'POST',
      body: JSON.stringify(data)
    });
  }

  createInvitation(email, role) {
    return this.request('/admin/invitations', {
      method: 'POST',
      body: JSON.stringify({ email, role })
    });
  }
}

window.apiClient = new ApiClient();
