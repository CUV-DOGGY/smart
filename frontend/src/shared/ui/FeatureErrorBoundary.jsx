import { Component } from 'react';

export class FeatureErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { failed: false };
  }

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error) {
    console.error('Feature rendering failed', error);
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <section className="feature-error" role="alert">
        <h2>{this.props.title || '页面暂时无法显示'}</h2>
        <p>{this.props.message || '页面遇到异常，请重试。'}</p>
        <button
          type="button"
          className="primary"
          onClick={() => this.setState({ failed: false })}
        >
          重新加载此页面
        </button>
      </section>
    );
  }
}
